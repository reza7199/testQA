"""GitHub client (MVP).

Preferred production approach: GitHub App installation tokens.
For MVP, you can use a PAT via UIQA_GITHUB_TOKEN.

This file implements:
- issue dedupe by searching for bug_id marker in open issues (placeholder)
- create issue (real POST if token provided; otherwise returns fake URL)

Swap this for:
- gh CLI
- Octokit (Node)
- or GitHub REST + better search & labeling
"""

from __future__ import annotations
import re
import httpx
from dataclasses import dataclass
from . import util
from ..settings import settings

@dataclass
class IssueResult:
    created: bool
    url: str

def _repo_from_url(repo_url: str) -> tuple[str,str] | None:
    # https://github.com/org/repo(.git)
    m = re.search(r"github\.com/([^/]+)/([^/]+?)(?:\.git)?$", repo_url)
    if not m:
        return None
    return m.group(1), m.group(2)

async def create_or_comment_issue(repo_url: str, bug: dict) -> IssueResult:
    parsed = _repo_from_url(repo_url)
    if not parsed:
        return IssueResult(created=False, url="")
    owner, repo = parsed

    # If no token, return a deterministic fake URL.
    if not settings.GITHUB_TOKEN:
        fake = f"https://github.com/{owner}/{repo}/issues/0#bug_id={bug['bug_id']}"
        return IssueResult(created=True, url=fake)

    title = f"[UI][{bug.get('test_type','suite').title()}] {bug.get('title','UI bug')}"
    body = util.issue_body(bug)

    url = f"https://api.github.com/repos/{owner}/{repo}/issues"
    headers = {
        "Authorization": f"token {settings.GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "uiqa-mvp",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(url, headers=headers, json={"title": title, "body": body, "labels": ["ui", "bug", bug.get("test_type","suite"), f"severity:{bug.get('severity','medium')}"]})
        resp.raise_for_status()
        data = resp.json()
        return IssueResult(created=True, url=data.get("html_url",""))
