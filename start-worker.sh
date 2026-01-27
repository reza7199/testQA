#!/bin/bash
cd /Users/navidkalantari/Desktop/Projects/uiqa_mvp_backend_ui_v2/backend
source uiqa_env/bin/activate
export PATH="$HOME/.npm-global/bin:$PATH"
export UIQA_DB_URL="sqlite:////Users/navidkalantari/Desktop/Projects/uiqa_mvp_backend_ui_v2/data/uiqa.sqlite"
export UIQA_REDIS_URL="redis://localhost:6379/0"
export UIQA_ARTIFACTS_DIR="/Users/navidkalantari/Desktop/Projects/uiqa_mvp_backend_ui_v2/artifacts"
celery -A app.worker.celery_app worker -l info
