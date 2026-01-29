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
import time

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
    """Send run to Celery queue."""
    print(f"📤 Sending task for run {run_id} to Celery...")
    celery_app.send_task("app.worker.process_run", args=[run_id])


@celery_app.task(name="app.worker.process_run")
def process_run(run_id: str):
    """Simple fake task processor for demo purposes."""
    print(f"🎯 Starting fake processing for run: {run_id}")
    
    from sqlalchemy.orm import Session
    from .db import SessionLocal
    from .models import Run, Bug, Artifact
    import json
    from datetime import datetime
    import time
    import traceback
    
    db = SessionLocal()
    run = None
    try:
        # 1. Find the run and mark as running
        run = db.query(Run).filter(Run.id == run_id).first()
        if not run:
            print(f"❌ Run {run_id} not found")
            return
        
        run.status = "running"
        run.started_at = datetime.utcnow()
        db.commit()  # ✅ مهم: اول commit کن
        
        # 2. Step 1: Clone repository (fake)
        print(f"📥 Step 1/5: Cloning repository (fake)")
        publish_step(run_id, "clone_repo", "started")
        publish_log(run_id, "info", "clone_repo", f"Cloning {run.repo_url} (branch: {run.branch})...")
        time.sleep(2)
        publish_step(run_id, "clone_repo", "finished")
        
        # 3. Step 2: Analyze repository (fake)
        print(f"🔍 Step 2/5: Analyzing repository (fake)")
        publish_step(run_id, "analyze_repo", "started")
        publish_log(run_id, "info", "analyze_repo", f"Analyzing structure: app_dir={run.app_dir}, ui_dir={run.ui_dir}")
        time.sleep(3)
        publish_step(run_id, "analyze_repo", "finished")
        
        # 4. Step 3: Generate tests (fake)
        print(f"🛠️ Step 3/5: Generating tests (fake)")
        publish_step(run_id, "generate_tests_docs", "started")
        publish_log(run_id, "info", "generate_tests_docs", f"Generating {run.suite} test suite...")
        time.sleep(2)
        publish_step(run_id, "generate_tests_docs", "finished")
        
        # 5. Step 4: Execute tests (fake)
        print(f"⚡ Step 4/5: Executing tests (fake)")
        publish_step(run_id, "execute_tests", "started")
        publish_log(run_id, "info", "execute_tests", "Running Playwright tests in headless mode...")
        time.sleep(4)
        
        # 6. Create bug record
        bug = Bug(
            run_id=run_id,
            bug_id=f"demo-bug-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}",
            timestamp=datetime.utcnow(),
            test_type=run.suite,
            workflow="page_load",
            severity="low",
            title="Demo: Page title could be more descriptive",
            expected="Page should have meaningful title related to application",
            actual="Title is generic 'React App' or 'localhost'",
            repro_steps="1. Navigate to http://localhost:3000\n2. Check page title in browser tab\n3. Title shows generic name",
            page_url="http://localhost:3000",
            console_errors=json.dumps([]),
            network_failures=json.dumps([]),
            confidence=75,
            github_issue_url=None
        )
        db.add(bug)
        
        # 7. Create fake artifact
        artifact = Artifact(
            run_id=run_id,
            type="log",
            path=f"/tmp/uiqa-demo-{run_id}.log",
            extra_metadata=json.dumps({
                "generated_at": datetime.utcnow().isoformat(),
                "test_count": 3,
                "duration_seconds": 15,
                "browser": "chromium",
                "note": "Demo artifact for presentation"
            })
        )
        db.add(artifact)
        
        # 8. Update run to completed - ✅ اینجا مهمه
        run.status = "completed"
        run.finished_at = datetime.utcnow()
        run.summary_json = json.dumps({
            "tests_executed": 3,
            "tests_passed": 2,
            "tests_failed": 1,
            "bugs_found": 1,
            "artifacts_generated": 1,
            "duration_seconds": 15,
            "mode": "demo",
            "message": "Demo run completed successfully",
            "recommendation": "Add descriptive page titles"
        })
        
        db.commit()  # ✅ commit مجدد
        
        publish_log(run_id, "success", "execute_tests", f"Tests completed: 3 total, 2 passed, 1 failed")
        publish_step(run_id, "execute_tests", "finished")
        
        # 9. Final steps
        print(f"💾 Step 5/5: Saving results")
        publish_step(run_id, "save_results", "started")
        publish_log(run_id, "info", "save_results", "Saving bugs and artifacts to database...")
        time.sleep(1)
        publish_step(run_id, "save_results", "finished")
        
        # 10. Done
        publish_step(run_id, "done", "finished")
        publish_log(run_id, "success", "done", f"Run {run_id[:8]}... completed successfully!")
        
        print(f"✅ Fake run {run_id} completed successfully")
        
    except Exception as e:
        print(f"❌ Error processing run {run_id}: {e}")
        traceback.print_exc()
        
        # Mark as failed
        if run:
            db.rollback()  # Rollback اول
            run.status = "failed"
            run.error_message = str(e)[:500]
            db.commit()
        
        publish_log(run_id, "error", "error", f"Processing failed: {str(e)[:200]}")
        publish_step(run_id, "done", "failed")
        
    finally:
        if db:
            db.close()
    
    return {"status": "completed", "run_id": run_id}
    
# For backward compatibility
def _process_run(self, run: Run):
    """Legacy function - not used in fake mode."""
    pass