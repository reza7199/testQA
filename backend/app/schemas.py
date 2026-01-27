from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict

class RunCreate(BaseModel):
    repo_url: str
    branch: str = "main"
    app_dir: str
    ui_dir: str
    suite: str = Field(default="both", pattern="^(smoke|regression|both)$")
    create_github_issues: bool = True
    commit_results: bool = False

class RunOut(BaseModel):
    id: str
    status: str
    created_at: datetime
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    repo_url: str
    branch: str
    commit_sha: Optional[str] = None
    app_dir: str
    ui_dir: str
    suite: str
    create_github_issues: bool
    commit_results: bool
    summary_json: Optional[Dict] = None
    error_message: Optional[str] = None

class BugOut(BaseModel):
    bug_id: str
    timestamp: datetime
    test_type: str
    workflow: str
    severity: str
    title: str
    expected: str
    actual: str
    repro_steps: str
    page_url: str
    console_errors: str
    network_failures: str
    trace_path: str
    screenshot_path: str
    video_path: str
    suspected_root_cause: str
    code_location_guess: str
    confidence: int
    github_issue_url: Optional[str] = None

class ArtifactOut(BaseModel):
    id: int
    type: str
    path: str
    metadata: Optional[Dict] = None

class IssueOut(BaseModel):
    bug_id: str
    issue_url: str


# Worker management schemas
class WorkerStatusOut(BaseModel):
    running: bool
    mode: str  # "local" or "docker"
    pid: Optional[int] = None
    uptime_seconds: Optional[float] = None
    log_tail: List[str] = []


class WorkerStartRequest(BaseModel):
    mode: str = Field(default="local", pattern="^(local|docker)$")
    api_key: Optional[str] = None  # Only used for docker mode


class WorkerActionResponse(BaseModel):
    success: bool
    error: Optional[str] = None
    pid: Optional[int] = None
    mode: Optional[str] = None
    logs: Optional[List[str]] = None


# Settings schemas
class SettingsOut(BaseModel):
    worker_mode: str = "local"  # "local" or "docker"
    anthropic_api_key: Optional[str] = None  # Masked for security
    github_token: Optional[str] = None  # Masked for security


class SettingsUpdate(BaseModel):
    worker_mode: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    github_token: Optional[str] = None
