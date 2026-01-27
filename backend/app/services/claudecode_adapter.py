"""Claude Code via MCP (Option A).

This module implements a real adapter that talks to Claude Code through an MCP server.

Minimal, production-friendly approach:
- Use MCP **stdio transport** to launch the Claude Code MCP server (recommended by the server author).
- Call the unified tool: `claude_code` with a one-shot prompt.
- Validate and return deterministic JSON.

Server used:
- @steipete/claude-code-mcp exposes a single tool `claude_code` that runs the Claude Code CLI
  with `--dangerously-skip-permissions`. (Requires one-time local CLI acceptance.)

Docs / references:
- MCP Python SDK (pip: mcp) supports stdio client sessions.
- The claude-code-mcp server documents the `claude_code` tool and npx usage.
"""

from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    steps: list[str]


def _read_optional_contract(repo_root: Path) -> Optional[str]:
    p = repo_root / "ui_contract.txt"
    if p.exists() and p.is_file():
        try:
            return p.read_text(encoding="utf-8")
        except Exception:
            return p.read_text(errors="ignore")
    return None


class ClaudeCodeMCPAdapter:
    """Adapter that calls Claude Code (through MCP) in one-shot mode."""

    def __init__(
        self,
        *,
        # You can override the command if you vendor the server.
        mcp_command: str | None = None,
        mcp_args: list[str] | None = None,
        env: dict[str, str] | None = None,
        timeout_s: int = 900,
    ):
        self.mcp_command = mcp_command or os.getenv("UIQA_CLAUDE_MCP_CMD", "npx")
        self.mcp_args = mcp_args or json.loads(
            os.getenv(
                "UIQA_CLAUDE_MCP_ARGS_JSON",
                json.dumps(["-y", "@steipete/claude-code-mcp@latest"]),
            )
        )
        self.env = env or {}
        self.timeout_s = int(os.getenv("UIQA_CLAUDE_MCP_TIMEOUT_S", str(timeout_s)))

    async def _call_claude_code_tool(self, prompt: str, tools: Optional[list[str]] = None) -> str:
        """Call the MCP tool and return raw text output."""
        server_params = StdioServerParameters(
            command=self.mcp_command,
            args=self.mcp_args,
            env={**os.environ, **self.env},
        )

        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                # Tool name is documented as `claude_code`. Some clients namespace it; MCP sdk uses raw names.
                tool_args: dict[str, Any] = {"prompt": prompt}
                if tools:
                    tool_args["options"] = {"tools": tools}

                result = await session.call_tool("claude_code", tool_args)
                # MCP results may be structured; we try best-effort extraction.
                if hasattr(result, "content") and result.content:
                    # Prefer first text chunk
                    for item in result.content:
                        if getattr(item, "type", None) == "text":
                            return item.text
                    # Fallback to string conversion
                    return str(result.content)
                return str(result)

    def call(self, prompt: str, tools: Optional[list[str]] = None) -> str:
        """Sync wrapper for Celery tasks.

        Handles the case where we're running inside a Celery worker which may
        have event loop complications with forked processes.
        """
        import concurrent.futures

        def run_async():
            # Create a fresh event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(
                    asyncio.wait_for(self._call_claude_code_tool(prompt, tools), timeout=self.timeout_s)
                )
            finally:
                loop.close()

        # Run in a separate thread to avoid event loop conflicts
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(run_async)
            return future.result(timeout=self.timeout_s + 30)

    # -------------------------
    # High-level operations used by the worker
    # -------------------------

    def _parse_json_response(self, raw: str, operation: str) -> dict[str, Any]:
        """Parse JSON from Claude Code response with better error handling."""
        import re
        import sys

        # Log raw response for debugging
        print(f"[{operation}] Raw response length: {len(raw)}", file=sys.stderr)
        if len(raw) < 2000:
            print(f"[{operation}] Raw response: {raw}", file=sys.stderr)
        else:
            print(f"[{operation}] Raw response (truncated): {raw[:1000]}...{raw[-500:]}", file=sys.stderr)

        if not raw or not raw.strip():
            raise ValueError(f"Empty response from Claude Code for {operation}")

        # Try direct parse first
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)\n?```', raw)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in the response
        brace_match = re.search(r'\{[\s\S]*\}', raw)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except json.JSONDecodeError:
                pass

        raise ValueError(f"Could not parse JSON from Claude Code response for {operation}. Raw: {raw[:500]}")

    def analyze_repo(self, repo_root: Path, app_dir: str, ui_dir: str) -> dict[str, Any]:
        contract = _read_optional_contract(repo_root)

        prompt = f"""You are Claude Code. You are operating INSIDE this git repo on disk.
Your job: analyze the repo and produce a strict JSON object (no markdown) describing:
1) how to start the UI app (best command + working dir) and which port it binds to by default
2) recommended smoke workflows (3-10) that cover core functionality
3) any existing E2E tooling/tests you detect (Playwright/Cypress/etc.)
4) whether stable selectors exist and where; propose selector strategy if not.

Constraints:
- Repo root: {repo_root}
- App folder: {app_dir}
- UI folder: {ui_dir}

If ui_contract.txt exists, it defines workflows. Here is its content (may be empty):
{contract or ""}

Output JSON schema:
{{
  "start": {{
    "cwd": "relative/path",
    "command": "npm run dev -- --port 4173",
    "baseUrl": "http://127.0.0.1:4173"
  }},
  "workflows": [{{"name": "...", "description": "...", "steps": ["...","..."]}}],
  "detected": {{
    "hasPlaywright": true|false,
    "hasCypress": true|false,
    "notes": "..."
  }},
  "selectors": {{
    "strategy": "data-testid",
    "notes": "..."
  }}
}}

Return ONLY valid JSON.
"""

        raw = self.call(prompt, tools=["Bash", "Read", "GrepTool", "GlobTool", "LS"])
        return self._parse_json_response(raw, "analyze_repo")

    def generate_tests_and_docs(
        self,
        repo_root: Path,
        ui_dir: str,
        workflows: list[dict[str, Any]],
        selector_strategy: str = "data-testid",
    ) -> dict[str, Any]:
        """Ask Claude Code to add Playwright tests + docs to the repo."""

        prompt = f"""You are Claude Code. You are operating inside this repo: {repo_root}

Goal:
- Ensure Playwright E2E tests exist under: {ui_dir}/ui-testing/
- Generate:
  - smoke tests (fast, minimal) and regression tests (broader)
  - a README.md in ui-testing/ describing how tests run, what they cover, and how to extend
  - selectors: if UI lacks stable selectors, add `data-testid` attributes minimally to key elements
    and document selector rules. Prefer adding test ids only where needed.
- If ui_contract workflows exist, implement tests for them. Workflows JSON:
{json.dumps(workflows, indent=2)}

Requirements:
- Tests must not be flaky: use explicit waits for navigation/loading states.
- Prefer role-based selectors first (getByRole), then data-testid when needed.
- Add Playwright config with:
  - baseURL MUST read from environment variable: `baseURL: process.env.BASE_URL || 'http://localhost:3000'`
  - webServer should have `reuseExistingServer: true` (server is started externally)
  - JSON reporter output to artifacts/playwright/results.json
  - traces/videos/screenshots on failure
  - Only include chromium project (skip firefox/webkit to avoid missing browser issues)
- Do not break existing lint/build.

Output JSON (no markdown):
{{
  "created": {{
     "testsDir": "{ui_dir}/ui-testing",
     "files": ["..."]
  }},
  "selectorChanges": {{
     "modifiedFiles": ["..."],
     "notes": "..."
  }}
}}

Return ONLY valid JSON.
"""

        raw = self.call(prompt, tools=["Bash", "Read", "Write", "Edit", "GrepTool", "GlobTool", "LS"])
        return self._parse_json_response(raw, "generate_tests_and_docs")

    def triage_failures(
        self,
        repo_root: Path,
        playwright_results_json: Path,
    ) -> dict[str, Any]:
        """Ask Claude Code to read Playwright results and produce deterministic bug list JSON."""
        prompt = f"""You are Claude Code in repo: {repo_root}

Read Playwright JSON results at:
{playwright_results_json}

Task:
- Produce a strict JSON list of bug records.
- Each bug record must include:
  - title
  - severity (blocker|critical|major|minor)
  - suite (smoke|regression)
  - repro_steps (list of strings)
  - expected
  - actual
  - evidence_paths (list of relative paths to screenshots/traces/videos if present)
  - suggested_fix (short)
  - component_guess (file/folder if you can infer)

Output schema:
{{
  "bugs": [
    {{
      "title": "...",
      "severity": "major",
      "suite": "smoke",
      "repro_steps": ["..."],
      "expected": "...",
      "actual": "...",
      "evidence_paths": ["..."],
      "suggested_fix": "...",
      "component_guess": "..."
    }}
  ]
}}

Return ONLY valid JSON.
"""
        raw = self.call(prompt, tools=["Read", "GrepTool", "GlobTool", "LS"])
        return self._parse_json_response(raw, "triage_failures")
