"""Playwright Runner (real implementation).

This runner is intentionally *repo-agnostic*:
- Detect package manager in the UI folder
- Install deps (best-effort)
- Start the UI dev server
- Run Playwright smoke + regression suites
- Save artifacts under the configured artifacts directory

Assumptions:
- Node.js 20+ available in the worker container
- Playwright browsers installed (Dockerfile does this) OR tests will install them
- The UI folder contains a package.json

Configuration knobs (env):
- UIQA_START_CMD: override start command (e.g. "pnpm dev -- --port {port}")
- UIQA_START_CWD: override start cwd relative to repo root
- UIQA_BASE_URL: override base url (otherwise inferred from port)
- UIQA_TEST_PROJECT: optionally limit Playwright project
- UIQA_NPM_INSTALL: set to "false" to skip install step

Generated outputs:
- playwright/results.json (JSON reporter)
- playwright/html-report (if configured)
- screenshots/videos/traces (per Playwright config)

"""

from __future__ import annotations

import json
import os
import random
import shlex
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class SuiteResult:
    suite: str
    ok: bool
    results_json: Path
    stdout_path: Path
    stderr_path: Path
    exit_code: int


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _detect_pkg_manager(ui_dir: Path) -> str:
    if (ui_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (ui_dir / "yarn.lock").exists():
        return "yarn"
    return "npm"


def _read_package_json(ui_dir: Path) -> dict:
    p = ui_dir / "package.json"
    return json.loads(p.read_text(encoding="utf-8"))


def _run(cmd: str, cwd: Path, env: dict[str, str], stdout_path: Path, stderr_path: Path, timeout_s: int) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as out, stderr_path.open("w", encoding="utf-8") as err:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            shell=True,
            stdout=out,
            stderr=err,
            text=True,
        )
        try:
            return proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            return 124


def _start_server(cmd: str, cwd: Path, env: dict[str, str], stdout_path: Path, stderr_path: Path) -> subprocess.Popen:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    out = stdout_path.open("w", encoding="utf-8")
    err = stderr_path.open("w", encoding="utf-8")
    return subprocess.Popen(cmd, cwd=str(cwd), env=env, shell=True, stdout=out, stderr=err, text=True)


def _wait_http_ok(url: str, timeout_s: int = 60) -> bool:
    import httpx
    start = time.time()
    while time.time() - start < timeout_s:
        try:
            r = httpx.get(url, timeout=3.0, follow_redirects=True)
            if r.status_code < 500:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


class PlaywrightRunner:
    def __init__(self, repo_root: Path, artifacts_dir: Path):
        self.repo_root = repo_root
        self.artifacts_dir = artifacts_dir

    def _default_start(self, ui_dir: Path, port: int) -> tuple[Path, str, str]:
        """Return (cwd, cmd, base_url)."""
        override_cmd = os.getenv("UIQA_START_CMD")
        override_cwd = os.getenv("UIQA_START_CWD")
        override_base = os.getenv("UIQA_BASE_URL")

        if override_cmd:
            cwd = self.repo_root / (override_cwd or str(ui_dir.relative_to(self.repo_root)))
            base = override_base or f"http://127.0.0.1:{port}"
            return cwd, override_cmd.format(port=port, baseUrl=base), base

        pkg = _detect_pkg_manager(ui_dir)
        pkg_json = _read_package_json(ui_dir)
        scripts = (pkg_json.get("scripts") or {})

        # prefer dev, then start
        if "dev" in scripts:
            if pkg == "npm":
                cmd = f"npm run dev -- --host 127.0.0.1 --port {port}"
            elif pkg == "pnpm":
                cmd = f"pnpm dev -- --host 127.0.0.1 --port {port}"
            else:
                cmd = f"yarn dev --host 127.0.0.1 --port {port}"
        elif "start" in scripts:
            # start often respects PORT env, but not always
            cmd = f"{pkg} run start"
        else:
            raise RuntimeError(f"No dev/start script found in {ui_dir}/package.json")

        base = override_base or f"http://127.0.0.1:{port}"
        return ui_dir, cmd, base

    def _copy_test_artifacts(self, pw_cwd: Path, dest_dir: Path) -> None:
        """Copy any test artifacts (traces, screenshots, videos) from the test folder to dest."""
        # Common artifact locations in Playwright projects
        artifact_patterns = [
            "test-results",
            "playwright-report",
            "artifacts",
        ]
        for pattern in artifact_patterns:
            src = pw_cwd / pattern
            if src.exists() and src.is_dir():
                for item in src.rglob("*"):
                    if item.is_file() and item.suffix in (".zip", ".png", ".webm", ".jpg", ".json"):
                        rel = item.relative_to(src)
                        dst = dest_dir / rel
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            shutil.copy2(item, dst)
                        except Exception:
                            pass

    def _install_deps(self, ui_dir: Path, run_id: str, log_prefix: str = "install") -> None:
        if os.getenv("UIQA_NPM_INSTALL", "true").lower() in ("0", "false", "no"):
            return
        pkg = _detect_pkg_manager(ui_dir)
        install_cmd = {"npm": "npm ci", "pnpm": "pnpm install --frozen-lockfile", "yarn": "yarn install --frozen-lockfile"}[pkg]

        out = self.artifacts_dir / f"{log_prefix}.stdout.txt"
        err = self.artifacts_dir / f"{log_prefix}.stderr.txt"
        code = _run(install_cmd, cwd=ui_dir, env=os.environ.copy(), stdout_path=out, stderr_path=err, timeout_s=1800)
        if code != 0:
            # fall back to non-ci install
            fallback = {"npm": "npm install", "pnpm": "pnpm install", "yarn": "yarn install"}[pkg]
            code2 = _run(fallback, cwd=ui_dir, env=os.environ.copy(), stdout_path=out, stderr_path=err, timeout_s=1800)
            if code2 != 0:
                raise RuntimeError(f"Dependency install failed (see {out} / {err})")

    def run_suite(self, *, ui_dir_rel: str, suite: str, run_id: str) -> SuiteResult:
        ui_dir = (self.repo_root / ui_dir_rel).resolve()
        if not (ui_dir / "package.json").exists():
            raise FileNotFoundError(f"UI folder missing package.json: {ui_dir}")

        self._install_deps(ui_dir, run_id)

        port = _find_free_port()
        start_cwd, start_cmd, base_url = self._default_start(ui_dir, port)

        server_out = self.artifacts_dir / f"server.{suite}.stdout.txt"
        server_err = self.artifacts_dir / f"server.{suite}.stderr.txt"

        env = os.environ.copy()
        env.setdefault("PORT", str(port))
        # Support older webpack/create-react-app projects with newer Node.js
        env.setdefault("NODE_OPTIONS", "--openssl-legacy-provider")
        # Set BASE_URL for Playwright tests to use our already-running server
        env["BASE_URL"] = base_url
        # Also set PLAYWRIGHT_BASE_URL as some configs use this
        env["PLAYWRIGHT_BASE_URL"] = base_url
        # Tell Playwright to reuse existing server (skip starting its own webServer)
        env["CI"] = "true"

        server = _start_server(start_cmd, cwd=start_cwd, env=env, stdout_path=server_out, stderr_path=server_err)

        try:
            if not _wait_http_ok(base_url, timeout_s=90):
                raise RuntimeError(f"UI server did not become ready at {base_url}. See {server_out} / {server_err}")

            # Run Playwright tests. We assume tests + config were generated under ui-testing/.
            # You can override location by setting UIQA_PLAYWRIGHT_CWD.
            pw_cwd = Path(os.getenv("UIQA_PLAYWRIGHT_CWD", str(ui_dir / "ui-testing")))
            if not pw_cwd.exists():
                raise FileNotFoundError(f"Playwright tests folder not found: {pw_cwd}. Generate tests first.")

            # Install Playwright test dependencies if a package.json exists in the test folder
            if (pw_cwd / "package.json").exists():
                self._install_deps(pw_cwd, run_id, log_prefix="install_tests")

            pw_output_dir = self.artifacts_dir / "playwright"
            pw_output_dir.mkdir(parents=True, exist_ok=True)
            results_json = self.artifacts_dir / f"playwright.{suite}.results.json"
            pw_stdout = self.artifacts_dir / f"playwright.{suite}.stdout.txt"
            pw_stderr = self.artifacts_dir / f"playwright.{suite}.stderr.txt"

            # Set output directory env var to ensure artifacts go to our folder
            env["PLAYWRIGHT_OUTPUT_DIR"] = str(pw_output_dir)

            # Run tests from the specific suite file (smoke.spec.ts/js or regression.spec.ts/js)
            project = os.getenv("UIQA_TEST_PROJECT")
            project_arg = f"--project {shlex.quote(project)}" if project else ""

            # Detect actual test file extension (.ts or .js)
            test_file = None
            for ext in [".spec.ts", ".spec.js", ".test.ts", ".test.js"]:
                candidate = pw_cwd / "tests" / f"{suite}{ext}"
                if candidate.exists():
                    test_file = f"tests/{suite}{ext}"
                    break

            if not test_file:
                # Fallback: let Playwright discover tests with grep pattern
                test_file = f"--grep {suite}"

            # Use --trace=on to capture traces, --output for artifacts directory
            cmd = f"npx playwright test {test_file} {project_arg} --reporter=json --output={shlex.quote(str(pw_output_dir))} --trace=on"
            # Note: JSON reporter writes to stdout by default; we capture it to file.
            code = _run(cmd, cwd=pw_cwd, env=env, stdout_path=pw_stdout, stderr_path=pw_stderr, timeout_s=1800)

            # If stdout contains JSON, save it as results_json too (fallback).
            try:
                txt = pw_stdout.read_text(encoding="utf-8").strip()
                if txt.startswith("{") and "tests" in txt:
                    results_json.write_text(txt, encoding="utf-8")
            except Exception:
                pass

            # Copy any artifacts from the test folder to our artifacts folder
            # (in case the Playwright config has its own outputDir)
            self._copy_test_artifacts(pw_cwd, pw_output_dir)

            return SuiteResult(
                suite=suite,
                ok=(code == 0),
                results_json=results_json,
                stdout_path=pw_stdout,
                stderr_path=pw_stderr,
                exit_code=code,
            )
        finally:
            try:
                server.terminate()
                server.wait(timeout=10)
            except Exception:
                try:
                    server.kill()
                except Exception:
                    pass
