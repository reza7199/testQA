# UIQA (Agentic UI QA) — Backend + Example UI

This repo contains:
- `backend/`: FastAPI API server + Celery worker (Redis broker) to run automated UI QA pipelines
- `ui/`: a simplified React + Vite UI that talks to the backend
- `docker-compose.yml`: brings up API, worker, and Redis

## What this MVP does
- UI triggers a "run" against a GitHub repo (URL + appDir + uiDir + suite)
- Backend enqueues a job and streams step-by-step events over SSE
- Worker executes a **placeholder pipeline** (clone → analyze → generate tests/docs → run smoke/regression → triage → create issues)
- Results are stored in SQLite and exposed via APIs:
  - run status
  - bugs list
  - CSV download
  - issues created
  - artifacts (local paths; you can swap to S3 later)

> The pipeline includes **clear extension points** for ClaudeCode integration and Playwright execution.

## Quickstart (Docker)
1. Ensure Docker Desktop is running.
2. From repo root:
   ```bash
   docker compose up --build
   ```
3. Open:
   - Backend: http://localhost:8000/docs
   - UI: http://localhost:5173

## Quickstart (local dev)
### Backend
```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal (worker):
```bash
cd backend
source .venv/bin/activate
celery -A app.worker.celery_app worker -l info
```

Run Redis:
```bash
docker run -p 6379:6379 redis:7
```

### UI
```bash
cd ui
npm install
npm run dev
```

## ClaudeCode + Playwright integration
See:
- `backend/app/services/claudecode_adapter.py`
- `backend/app/services/playwright_runner.py`
- `backend/app/services/github_client.py`

They are designed so you can replace the placeholder logic with real calls:
- ClaudeCode: repo comprehension + test/doc generation + triage
- Playwright: run tests and collect traces/videos/screenshots

## Notes
- This MVP uses SQLite for metadata (file: `backend/uiqa.sqlite` in container). Swap to Postgres when ready.
- Artifacts are stored under `backend/artifacts/<run_id>/`.


## Claude Code + MCP (Option A)

This MVP now includes a real Claude Code adapter that uses the MCP Python SDK (`mcp`) to launch the
Claude Code MCP server via `npx` and call its unified `claude_code` tool.

Prereqs (one-time on the machine running the worker container):
- Node.js 20+ (already used by the Dockerfile)
- Claude Code CLI installed and authenticated:
  - `npm install -g @anthropic-ai/claude-code`
  - run once: `claude --dangerously-skip-permissions` and accept prompts
- The MCP server is invoked via: `npx -y @steipete/claude-code-mcp@latest` citeturn3view0
- The MCP client code follows the official MCP Python SDK stdio client pattern. citeturn2view0

If you prefer to not launch the MCP server per run, you can run it as a long-lived service and
switch the adapter to HTTP transport later (the MCP docs describe remote server connections). citeturn2view0

## Playwright in Docker

The backend Dockerfile was updated to:
- base on `node:20-bookworm`
- install Playwright browsers with `npx playwright install --with-deps` (see Playwright Docker docs). citeturn4search0

