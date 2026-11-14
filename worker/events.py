"""Run events over Redis: pub/sub for live streaming plus a capped list for replay,
so a browser that connects late (or reconnects after a refresh) sees the whole run."""
from __future__ import annotations

import json
import time
from functools import lru_cache

import redis

from common.config import env

MAX_EVENTS = 400


@lru_cache(maxsize=1)
def r() -> redis.Redis:
    return redis.Redis.from_url(env("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


def publish(thread_id: str, user_id: str, event: dict) -> None:
    event = {**event, "thread_id": thread_id, "ts": time.time()}
    data = json.dumps(event, default=str)
    pipe = r().pipeline()
    pipe.rpush(f"events:{thread_id}", data)
    pipe.ltrim(f"events:{thread_id}", -MAX_EVENTS, -1)
    pipe.expire(f"events:{thread_id}", 60 * 60 * 24 * 3)
    pipe.publish(f"chan:{thread_id}", data)
    pipe.publish(f"user:{user_id}", data)
    pipe.execute()


def history(thread_id: str) -> list[dict]:
    return [json.loads(x) for x in r().lrange(f"events:{thread_id}", 0, -1)]
