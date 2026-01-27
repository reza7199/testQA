import json
import redis
from .settings import settings

def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

def publish_event(run_id: str, payload: dict) -> None:
    r = get_redis()
    r.publish(f"uiqa:events:{run_id}", json.dumps(payload))

def publish_log(run_id: str, message: str, step: str | None = None, level: str = "info") -> None:
    publish_event(run_id, {"type": "log", "level": level, "step": step, "message": message})

def publish_step(run_id: str, step: str, status: str, extra: dict | None = None) -> None:
    payload = {"type": "step", "step": step, "status": status}
    if extra:
        payload.update(extra)
    publish_event(run_id, payload)
