from __future__ import annotations
from celery import Celery
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import uuid
import os
import hashlib
import traceback
import json

from sqlalchemy.orm import Session
from .settings import settings
from .db import SessionLocal, engine, Base
from .models import Run, Bug, Artifact, IssueRef
from .events import publish_step, publish_log
from .services.claudecode_adapter import ClaudeCodeMCPAdapter
from .services.playwright_runner import PlaywrightRunner
from .services.csv_writer import write_bugs_csv
from .services.github_client import create_or_comment_issue

Base.metadata.create_all(bind=engine)

celery_app = Celery(
    "uiqa",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)


def _extract_bugs_from_playwright_json(results_json: Path, suite: str) -> list[dict]:
    """Fallback: extract bugs directly from Playwright JSON when Claude Code triage fails."""
    bugs = []
    try:
        if not results_json.exists():
            return bugs
        data = json.loads(results_json.read_text(encoding="utf-8"))

        # Playwright JSON structure has suites -> specs -> tests -> results
        for suite_data in data.get("suites", []):
            for spec in suite_data.get("specs", []):
                for test in spec.get("tests", []):
                    for result in test.get("results", []):
                        if result.get("status") in ("failed", "timedOut"):
                            # Extract error message
                            error_msg = ""
                            if result.get("error", {}).get("message"):
                                error_msg = result["error"]["message"]
                            elif result.get("errors"):
                                error_msg = result["errors"][0].get("message", "") if result["errors"] else ""

                            title = f"{spec.get('title', 'Unknown test')} - {test.get('title', '')}"
                            bugs.append({
                                "title": title[:200],
                                "severity": "major",
                                "suite": suite,
                                "repro_steps": [f"Run test: {title}"],
                                "expected": "Test should pass",
                                "actual": error_msg[:500] if error_msg else f"Test {result.get('status', 'failed')}",
                                "evidence_paths": [a.get("path", "") for a in result.get("attachments", []) if a.get("path")],
                                "suggested_fix": "Review the test failure and fix the underlying issue",
                                "component_guess": spec.get("file", ""),
                            })
    except Exception as e:
        print(f"[fallback_triage] Error parsing Playwright JSON: {e}", file=__import__("sys").stderr)
    return bugs


def enqueue_run(run_id: str) -> None:
    celery_app.send_task("app.worker.process_run", args=[run_id])

@celery_app.task(name="app.worker.process_run")
def process_run(run_id: str):
    db = SessionLocal()
    try:
        _process_run(db, run_id)
    finally:
        db.close()

def _process_run(db: Session, run_id: str):
    run = db.query(Run).filter(Run.id == run_id).first()
    if not run:
        return

    run.status = "running"
    run.started_at = datetime.utcnow()
    db.commit()

    artifacts_root = Path(settings.ARTIFACTS_DIR) / run_id
    artifacts_root.mkdir(parents=True, exist_ok=True)

    work_root = Path("/tmp") / f"uiqa-work-{run_id}"
    if work_root.exists():
        shutil.rmtree(work_root)
    # Don't create directory - git clone will create it

    try:
        publish_step(run_id, "clone_repo", "started")
        publish_log(run_id, f"Cloning {run.repo_url} (branch {run.branch})...", "clone_repo")
        subprocess.run(["git", "clone", "--depth", "1", "--branch", run.branch, run.repo_url, str(work_root)], check=True, timeout=300)
        publish_step(run_id, "clone_repo", "finished")

        adapter = ClaudeCodeMCPAdapter()
        runner = PlaywrightRunner(work_root, artifacts_root)

        publish_step(run_id, "analyze_repo", "started")
        analysis = adapter.analyze_repo(work_root, run.app_dir, run.ui_dir)
        publish_log(run_id, f"Detected start: {analysis.get('start',{})}", "analyze_repo")
        publish_step(run_id, "analyze_repo", "finished")

        workflows = analysis.get("workflows") or []
        selector_strategy = (analysis.get("selectors") or {}).get("strategy") or "data-testid"

        publish_step(run_id, "generate_tests_docs", "started")
        gen = adapter.generate_tests_and_docs(work_root, run.ui_dir, workflows, selector_strategy=selector_strategy)
        publish_log(run_id, f"Generated files: {len((gen.get('created') or {}).get('files', []))}", "generate_tests_docs")
        publish_step(run_id, "generate_tests_docs", "finished")

        # Run suites
        suite_results = []
        if run.suite in ("smoke", "both"):
            publish_step(run_id, "run_smoke", "started")
            sr = runner.run_suite(ui_dir_rel=run.ui_dir, suite="smoke", run_id=run_id)
            suite_results.append(sr)
            publish_step(run_id, "run_smoke", "finished", {"ok": sr.ok, "exit_code": sr.exit_code})

        if run.suite in ("regression", "both"):
            publish_step(run_id, "run_regression", "started")
            rr = runner.run_suite(ui_dir_rel=run.ui_dir, suite="regression", run_id=run_id)
            suite_results.append(rr)
            publish_step(run_id, "run_regression", "finished", {"ok": rr.ok, "exit_code": rr.exit_code})

        # Triage failures (only on failing suites)
        publish_step(run_id, "triage", "started")
        bugs = []
        for sr in suite_results:
            if sr.ok:
                continue

            # Try Claude Code triage first
            triage_bugs = []
            try:
                triage = adapter.triage_failures(work_root, sr.results_json)
                triage_bugs = triage.get("bugs", [])
            except Exception as e:
                publish_log(run_id, f"Claude Code triage failed: {e}", "triage")

            # Fallback: extract bugs directly from Playwright JSON if triage returned empty
            if not triage_bugs:
                publish_log(run_id, f"Using fallback bug extraction for {sr.suite}", "triage")
                triage_bugs = _extract_bugs_from_playwright_json(sr.results_json, sr.suite)

            for b in triage_bugs:
                title = b.get("title", "").strip() or f"UI test failure ({sr.suite})"
                bug_id = hashlib.sha1(f"{sr.suite}:{title}".encode("utf-8")).hexdigest()[:12]
                bugs.append({
                    "bug_id": bug_id,
                    "test_type": sr.suite,
                    "workflow": "",
                    "severity": b.get("severity", "major"),
                    "title": title,
                    "expected": b.get("expected", ""),
                    "actual": b.get("actual", ""),
                    "repro_steps": "\n".join(b.get("repro_steps", []) if isinstance(b.get("repro_steps"), list) else [str(b.get("repro_steps",""))]),
                    "page_url": "",
                    "console_errors": "",
                    "network_failures": "",
                    "trace_path": "\n".join(b.get("evidence_paths", []) if isinstance(b.get("evidence_paths"), list) else []),
                    "screenshot_path": "",
                    "video_path": "",
                    "suspected_root_cause": b.get("suggested_fix", ""),
                    "code_location_guess": b.get("component_guess", ""),
                    "confidence": 70,
                })
        publish_log(run_id, f"Triage produced {len(bugs)} bugs.", "triage")
        publish_step(run_id, "triage", "finished", {"bugs": len(bugs)})

        # Persist bugs + write CSV
        for b in bugs:
            db.add(Bug(
                run_id=run_id,
                bug_id=b["bug_id"],
                test_type=b.get("test_type","smoke"),
                workflow=b.get("workflow",""),
                severity=b.get("severity","medium"),
                title=b.get("title",""),
                expected=b.get("expected",""),
                actual=b.get("actual",""),
                repro_steps=b.get("repro_steps",""),
                page_url=b.get("page_url",""),
                console_errors=b.get("console_errors",""),
                network_failures=b.get("network_failures",""),
                trace_path=b.get("trace_path",""),
                screenshot_path=b.get("screenshot_path",""),
                video_path=b.get("video_path",""),
                suspected_root_cause=b.get("suspected_root_cause",""),
                code_location_guess=b.get("code_location_guess",""),
                confidence=int(b.get("confidence",70)),
            ))
        db.commit()

        csv_path = artifacts_root / "bugs.csv"
        write_bugs_csv(csv_path, bugs)
        db.add(Artifact(run_id=run_id, type="csv", path=str(csv_path), extra_metadata=None))
        db.commit()

        # Create issues (optional)
        if run.create_github_issues and bugs:
            publish_step(run_id, "github_issues", "started")
            import asyncio
            async def _do():
                created = 0
                for b in bugs:
                    res = await create_or_comment_issue(run.repo_url, b)
                    if res.url:
                        created += 1
                        # Update DB entries with URL
                        bug_row = db.query(Bug).filter(Bug.run_id==run_id, Bug.bug_id==b["bug_id"]).first()
                        if bug_row:
                            bug_row.github_issue_url = res.url
                        db.add(IssueRef(run_id=run_id, bug_id=b["bug_id"], issue_url=res.url))
                        db.commit()
                return created
            created = asyncio.run(_do())
            publish_step(run_id, "github_issues", "finished", {"issues_created": created})

        # Finish
        run.status = "succeeded"
        run.finished_at = datetime.utcnow()
        run.summary_json = {
            "suites": [{"suite": sr.suite, "ok": sr.ok, "exit_code": sr.exit_code} for sr in suite_results],
            "bugs": len(bugs),
        }
        db.commit()

        publish_step(run_id, "done", "finished", {"status": "succeeded"})
    except subprocess.CalledProcessError as e:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        run.error_message = f"Command failed: {e}"
        db.commit()
        publish_step(run_id, "done", "finished", {"status": "failed"})
        publish_log(run_id, run.error_message, "error", level="error")
    except Exception as e:
        run.status = "failed"
        run.finished_at = datetime.utcnow()
        tb = traceback.format_exc()
        run.error_message = f"{str(e)}\n\nTraceback:\n{tb}"
        db.commit()
        publish_step(run_id, "done", "finished", {"status": "failed"})
        publish_log(run_id, run.error_message, "error", level="error")
