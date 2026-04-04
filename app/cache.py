import json
import os
from typing import Any

import redis

_DEFAULT_TTL = 60  # seconds

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "localhost"),
            port=int(os.environ.get("REDIS_PORT", 6379)),
            decode_responses=True,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
    return _client


def get_cache(key: str):
    try:
        value = get_redis().get(key)
        if value is None:
            return None
        return json.loads(value)
    except Exception:
        return None


def set_cache(key: str, value: Any, ttl: int = _DEFAULT_TTL) -> None:
    try:
        get_redis().setex(key, ttl, json.dumps(value))
    except Exception:
        pass


def delete_cache(key: str) -> None:
    try:
        get_redis().delete(key)
    except Exception:
        pass


def delete_cache_pattern(pattern: str) -> None:
    try:
        r = get_redis()
        cursor = 0
        while True:
            cursor, keys = r.scan(cursor, match=pattern, count=100)
            if keys:
                r.delete(*keys)
            if cursor == 0:
                break
    except Exception:
        pass
