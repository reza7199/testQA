from __future__ import annotations
from sqlalchemy import String, DateTime, Text, Integer, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from .db import Base

class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    status: Mapped[str] = mapped_column(String, default="queued")  # queued|running|failed|succeeded|cancelled
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    repo_url: Mapped[str] = mapped_column(String)
    branch: Mapped[str] = mapped_column(String, default="main")
    commit_sha: Mapped[str | None] = mapped_column(String, nullable=True)

    app_dir: Mapped[str] = mapped_column(String)
    ui_dir: Mapped[str] = mapped_column(String)
    suite: Mapped[str] = mapped_column(String, default="both")  # smoke|regression|both

    create_github_issues: Mapped[int] = mapped_column(Integer, default=1)
    commit_results: Mapped[int] = mapped_column(Integer, default=0)

    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    bugs: Mapped[list["Bug"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    artifacts: Mapped[list["Artifact"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    issues: Mapped[list["IssueRef"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Bug(Base):
    __tablename__ = "bugs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    bug_id: Mapped[str] = mapped_column(String)  # stable hash
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    test_type: Mapped[str] = mapped_column(String)  # smoke|regression
    workflow: Mapped[str] = mapped_column(String, default="")
    severity: Mapped[str] = mapped_column(String, default="medium")  # blocker|high|medium|low

    title: Mapped[str] = mapped_column(String)
    expected: Mapped[str] = mapped_column(Text, default="")
    actual: Mapped[str] = mapped_column(Text, default="")
    repro_steps: Mapped[str] = mapped_column(Text, default="")
    page_url: Mapped[str] = mapped_column(String, default="")

    console_errors: Mapped[str] = mapped_column(Text, default="")
    network_failures: Mapped[str] = mapped_column(Text, default="")

    trace_path: Mapped[str] = mapped_column(String, default="")
    screenshot_path: Mapped[str] = mapped_column(String, default="")
    video_path: Mapped[str] = mapped_column(String, default="")

    suspected_root_cause: Mapped[str] = mapped_column(Text, default="")
    code_location_guess: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Integer, default=70)  # store as int 0-100

    github_issue_url: Mapped[str | None] = mapped_column(String, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="bugs")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    type: Mapped[str] = mapped_column(String)  # trace|video|screenshot|report|csv|log|diff
    path: Mapped[str] = mapped_column(String)
    extra_metadata: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    run: Mapped["Run"] = relationship(back_populates="artifacts")


class IssueRef(Base):
    __tablename__ = "issues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"))
    bug_id: Mapped[str] = mapped_column(String)
    issue_url: Mapped[str] = mapped_column(String)

    run: Mapped["Run"] = relationship(back_populates="issues")


class AppSettings(Base):
    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String, unique=True)
    value: Mapped[str] = mapped_column(Text, default="")
