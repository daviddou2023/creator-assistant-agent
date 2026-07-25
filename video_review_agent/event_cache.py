"""SSE event cache backends.

Redis is the production backend. A memory fallback keeps local tests runnable
when Redis is not installed or not started.
"""

from __future__ import annotations

import json
import threading
from typing import Any, Protocol

from video_review_agent.config import PersistenceConfig


class SSEEventCache(Protocol):
    backend_name: str

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        ...

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        ...


class InMemorySSEEventCache:
    backend_name = "memory"

    def __init__(self, max_events: int = 500) -> None:
        self.max_events = max_events
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        with self._lock:
            events = self._events.setdefault(job_id, [])
            events.append(event)
            if len(events) > self.max_events:
                del events[: len(events) - self.max_events]

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(job_id, []))


class RedisSSEEventCache:
    backend_name = "redis"

    def __init__(
        self,
        redis_url: str,
        *,
        ttl_seconds: int = 86400,
        max_events: int = 500,
    ) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - depends on optional package
            raise RuntimeError("redis package is required for Redis SSE event cache.") from exc

        self.client = redis.Redis.from_url(redis_url, decode_responses=True)
        self.client.ping()
        self.ttl_seconds = ttl_seconds
        self.max_events = max_events

    def _key(self, job_id: str) -> str:
        return f"video_review_agent:sse:{job_id}"

    def append_event(self, job_id: str, event: dict[str, Any]) -> None:
        key = self._key(job_id)
        encoded = json.dumps(event, ensure_ascii=False)
        pipe = self.client.pipeline()
        pipe.rpush(key, encoded)
        pipe.ltrim(key, -self.max_events, -1)
        pipe.expire(key, self.ttl_seconds)
        pipe.execute()

    def get_events(self, job_id: str) -> list[dict[str, Any]]:
        raw_events = self.client.lrange(self._key(job_id), 0, -1)
        events: list[dict[str, Any]] = []
        for raw in raw_events:
            try:
                events.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        return events


def build_event_cache(config: PersistenceConfig) -> SSEEventCache:
    backend = config.event_cache_backend
    if backend in {"redis", "auto"}:
        try:
            return RedisSSEEventCache(
                config.redis_url,
                ttl_seconds=config.event_cache_ttl_seconds,
                max_events=config.event_cache_max_events,
            )
        except Exception:
            if backend == "redis":
                raise

    return InMemorySSEEventCache(max_events=config.event_cache_max_events)
