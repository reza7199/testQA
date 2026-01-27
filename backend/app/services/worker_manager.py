"""Worker Manager Service.

Manages the Celery worker process lifecycle from the API.
Supports two modes:
- Local: Uses Claude Max subscription (macOS Keychain)
- Docker (API Key): Uses ANTHROPIC_API_KEY environment variable
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..settings import settings


@dataclass
class WorkerStatus:
    running: bool
    mode: str  # "local" or "docker"
    pid: Optional[int]
    uptime_seconds: Optional[float]
    log_tail: list[str]


class WorkerManager:
    """Singleton manager for the Celery worker process."""

    _instance: Optional["WorkerManager"] = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._process: Optional[subprocess.Popen] = None
        self._mode: str = "local"
        self._start_time: Optional[float] = None
        self._logs: deque = deque(maxlen=500)
        self._log_thread: Optional[threading.Thread] = None
        self._stop_logging = threading.Event()

    def _get_project_root(self) -> Path:
        """Get the project root directory."""
        # Go up from backend/app/services to project root
        return Path(__file__).parent.parent.parent.parent.parent

    def _get_backend_dir(self) -> Path:
        """Get the backend directory."""
        return Path(__file__).parent.parent.parent

    def _read_logs(self):
        """Background thread to read process output."""
        if not self._process:
            return
        try:
            for line in iter(self._process.stdout.readline, ''):
                if self._stop_logging.is_set():
                    break
                if line:
                    self._logs.append(line.rstrip())
        except Exception:
            pass

    def get_status(self) -> WorkerStatus:
        """Get current worker status."""
        running = False
        pid = None
        uptime = None

        if self._process:
            poll = self._process.poll()
            if poll is None:
                running = True
                pid = self._process.pid
                if self._start_time:
                    uptime = time.time() - self._start_time
            else:
                # Process has ended
                self._process = None
                self._start_time = None

        return WorkerStatus(
            running=running,
            mode=self._mode,
            pid=pid,
            uptime_seconds=uptime,
            log_tail=list(self._logs)[-100:],
        )

    def start(self, mode: str = "local", api_key: Optional[str] = None) -> dict:
        """Start the worker process.

        Args:
            mode: "local" or "docker"
            api_key: Anthropic API key (only used in docker mode)
        """
        status = self.get_status()
        if status.running:
            return {"success": False, "error": "Worker is already running"}

        self._mode = mode
        self._logs.clear()
        self._stop_logging.clear()

        project_root = self._get_project_root()
        backend_dir = self._get_backend_dir()

        # Build environment
        env = os.environ.copy()
        env["UIQA_DB_URL"] = settings.DB_URL
        env["UIQA_REDIS_URL"] = settings.REDIS_URL
        env["UIQA_ARTIFACTS_DIR"] = settings.ARTIFACTS_DIR

        if mode == "docker" and api_key:
            env["ANTHROPIC_API_KEY"] = api_key

        # Add npm global bin to PATH for Claude CLI
        npm_global = Path.home() / ".npm-global" / "bin"
        if npm_global.exists():
            env["PATH"] = f"{npm_global}:{env.get('PATH', '')}"

        # Find venv python/celery
        venv_dir = backend_dir / "uiqa_env"
        if venv_dir.exists():
            celery_bin = venv_dir / "bin" / "celery"
            if not celery_bin.exists():
                return {"success": False, "error": f"Celery not found in venv: {celery_bin}"}
        else:
            # Fall back to system celery
            celery_bin = "celery"

        cmd = [
            str(celery_bin),
            "-A", "app.worker.celery_app",
            "worker",
            "-l", "info",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                cwd=str(backend_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._start_time = time.time()

            # Start log reader thread
            self._log_thread = threading.Thread(target=self._read_logs, daemon=True)
            self._log_thread.start()

            # Wait briefly and check if it started
            time.sleep(1)
            if self._process.poll() is not None:
                return {"success": False, "error": "Worker failed to start", "logs": list(self._logs)}

            return {"success": True, "pid": self._process.pid, "mode": mode}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def stop(self) -> dict:
        """Stop the worker process."""
        if not self._process:
            return {"success": False, "error": "Worker is not running"}

        try:
            self._stop_logging.set()

            # Try graceful shutdown first
            self._process.terminate()
            try:
                self._process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                # Force kill
                self._process.kill()
                self._process.wait(timeout=5)

            self._process = None
            self._start_time = None
            return {"success": True}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_logs(self, lines: int = 100) -> list[str]:
        """Get recent log lines."""
        return list(self._logs)[-lines:]


# Global instance
worker_manager = WorkerManager()
