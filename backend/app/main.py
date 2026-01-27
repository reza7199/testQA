from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from sqlalchemy.orm import Session
from pathlib import Path
import json
import uuid
import redis

from .settings import settings
from .db import get_db, engine, Base
from .models import Run, Bug, Artifact, IssueRef, AppSettings
from .schemas import (
    RunCreate, RunOut, BugOut, ArtifactOut, IssueOut,
    WorkerStatusOut, WorkerStartRequest, WorkerActionResponse,
    SettingsOut, SettingsUpdate
)
from .worker import enqueue_run
from .events import get_redis
from .services.worker_manager import worker_manager

Base.metadata.create_all(bind=engine)

app = FastAPI(title="UIQA MVP", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/api/runs", response_model=RunOut)
def create_run(payload: RunCreate, db: Session = Depends(get_db)):
    run_id = str(uuid.uuid4())
    run = Run(
        id=run_id,
        repo_url=payload.repo_url.strip(),
        branch=payload.branch.strip(),
        app_dir=payload.app_dir.strip(),
        ui_dir=payload.ui_dir.strip(),
        suite=payload.suite,
        create_github_issues=1 if payload.create_github_issues else 0,
        commit_results=1 if payload.commit_results else 0,
        status="queued",
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    enqueue_run(run_id)
    return _run_out(run)

@app.get("/api/runs", response_model=list[RunOut])
def list_runs(db: Session = Depends(get_db)):
    runs = db.query(Run).order_by(Run.created_at.desc()).limit(50).all()
    return [_run_out(r) for r in runs]

@app.get("/api/runs/{run_id}", response_model=RunOut)
def get_run(run_id: str, db: Session = Depends(get_db)):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_out(run)

@app.get("/api/runs/{run_id}/bugs", response_model=list[BugOut])
def get_bugs(run_id: str, db: Session = Depends(get_db)):
    bugs = db.query(Bug).filter(Bug.run_id == run_id).order_by(Bug.timestamp.asc()).all()
    return [BugOut(
        bug_id=b.bug_id, timestamp=b.timestamp, test_type=b.test_type, workflow=b.workflow, severity=b.severity,
        title=b.title, expected=b.expected, actual=b.actual, repro_steps=b.repro_steps, page_url=b.page_url,
        console_errors=b.console_errors, network_failures=b.network_failures,
        trace_path=b.trace_path, screenshot_path=b.screenshot_path, video_path=b.video_path,
        suspected_root_cause=b.suspected_root_cause, code_location_guess=b.code_location_guess,
        confidence=int(b.confidence), github_issue_url=b.github_issue_url
    ) for b in bugs]

@app.get("/api/runs/{run_id}/bugs.csv")
def download_bugs_csv(run_id: str):
    path = Path("artifacts") / run_id / "bugs.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="CSV not found for this run")
    return FileResponse(path, media_type="text/csv", filename=f"bugs_{run_id}.csv")

@app.get("/api/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: str, db: Session = Depends(get_db)):
    arts = db.query(Artifact).filter(Artifact.run_id == run_id).all()
    return [ArtifactOut(id=a.id, type=a.type, path=a.path, metadata=a.extra_metadata) for a in arts]

@app.get("/api/runs/{run_id}/issues", response_model=list[IssueOut])
def list_issues(run_id: str, db: Session = Depends(get_db)):
    issues = db.query(IssueRef).filter(IssueRef.run_id == run_id).all()
    return [IssueOut(bug_id=i.bug_id, issue_url=i.issue_url) for i in issues]

@app.get("/api/runs/{run_id}/events")
def stream_events(run_id: str):
    r = get_redis()
    pubsub = r.pubsub()
    channel = f"uiqa:events:{run_id}"
    pubsub.subscribe(channel)

    def gen():
        # SSE format: "data: <json>\n\n"
        yield "retry: 1000\n\n"
        for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            data = msg.get("data")
            yield f"data: {data}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")

def _run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id, status=r.status, created_at=r.created_at, started_at=r.started_at, finished_at=r.finished_at,
        repo_url=r.repo_url, branch=r.branch, commit_sha=r.commit_sha,
        app_dir=r.app_dir, ui_dir=r.ui_dir, suite=r.suite,
        create_github_issues=bool(r.create_github_issues), commit_results=bool(r.commit_results),
        summary_json=r.summary_json, error_message=r.error_message
    )


# =====================
# Worker Management API
# =====================

@app.get("/api/worker/status", response_model=WorkerStatusOut)
def get_worker_status():
    """Get current worker status."""
    status = worker_manager.get_status()
    return WorkerStatusOut(
        running=status.running,
        mode=status.mode,
        pid=status.pid,
        uptime_seconds=status.uptime_seconds,
        log_tail=status.log_tail,
    )


@app.post("/api/worker/start", response_model=WorkerActionResponse)
def start_worker(req: WorkerStartRequest, db: Session = Depends(get_db)):
    """Start the worker process."""
    # Get API key from settings if docker mode and not provided
    api_key = req.api_key
    if req.mode == "docker" and not api_key:
        setting = db.query(AppSettings).filter(AppSettings.key == "anthropic_api_key").first()
        if setting:
            api_key = setting.value

    result = worker_manager.start(mode=req.mode, api_key=api_key)
    return WorkerActionResponse(**result)


@app.post("/api/worker/stop", response_model=WorkerActionResponse)
def stop_worker():
    """Stop the worker process."""
    result = worker_manager.stop()
    return WorkerActionResponse(**result)


@app.get("/api/worker/logs")
def get_worker_logs(lines: int = 100):
    """Get recent worker logs."""
    return {"logs": worker_manager.get_logs(lines)}


# =====================
# Settings API
# =====================

def _mask_key(key: str | None) -> str | None:
    """Mask API key for display."""
    if not key:
        return None
    if len(key) < 12:
        return "***"
    return f"{key[:8]}...{key[-4:]}"


def _get_setting(db: Session, key: str) -> str | None:
    """Get a setting value."""
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()
    return setting.value if setting else None


def _set_setting(db: Session, key: str, value: str):
    """Set a setting value."""
    setting = db.query(AppSettings).filter(AppSettings.key == key).first()
    if setting:
        setting.value = value
    else:
        db.add(AppSettings(key=key, value=value))
    db.commit()


@app.get("/api/settings", response_model=SettingsOut)
def get_settings(db: Session = Depends(get_db)):
    """Get application settings (API keys are masked)."""
    return SettingsOut(
        worker_mode=_get_setting(db, "worker_mode") or "local",
        anthropic_api_key=_mask_key(_get_setting(db, "anthropic_api_key")),
        github_token=_mask_key(_get_setting(db, "github_token")),
    )


@app.put("/api/settings", response_model=SettingsOut)
def update_settings(updates: SettingsUpdate, db: Session = Depends(get_db)):
    """Update application settings."""
    if updates.worker_mode is not None:
        _set_setting(db, "worker_mode", updates.worker_mode)
    if updates.anthropic_api_key is not None:
        _set_setting(db, "anthropic_api_key", updates.anthropic_api_key)
    if updates.github_token is not None:
        _set_setting(db, "github_token", updates.github_token)

    return SettingsOut(
        worker_mode=_get_setting(db, "worker_mode") or "local",
        anthropic_api_key=_mask_key(_get_setting(db, "anthropic_api_key")),
        github_token=_mask_key(_get_setting(db, "github_token")),
    )
