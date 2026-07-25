"""Configuration helpers.

Secrets are intentionally read from environment variables only. Keep API keys out of
source files and documentation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_environment(env_path: str = ".env") -> None:
    """Load local .env values without overwriting existing environment values."""

    try:
        from dotenv import load_dotenv

        load_dotenv(env_path, override=False)
        return
    except Exception:
        pass

    path = Path(env_path)
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


@dataclass(frozen=True)
class LLMConfig:
    provider: str = "deepseek"
    model: str = "deepseek-v4-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"

    @property
    def enabled(self) -> bool:
        return bool(os.getenv(self.api_key_env))


def get_llm_config() -> LLMConfig:
    load_environment()
    return LLMConfig(
        provider=os.getenv("VIDEO_REVIEW_LLM_PROVIDER", "deepseek"),
        model=os.getenv("VIDEO_REVIEW_LLM_MODEL", "deepseek-v4-flash"),
        api_key_env=os.getenv("VIDEO_REVIEW_LLM_API_KEY_ENV", "DEEPSEEK_API_KEY"),
    )


@dataclass(frozen=True)
class PersistenceConfig:
    job_db_path: str = "local_data/review_jobs.sqlite3"
    checkpoint_backend: str = "sqlite"
    checkpoint_db_path: str = "local_data/langgraph_checkpoints.sqlite3"
    event_cache_backend: str = "auto"
    redis_url: str = "redis://localhost:6379/0"
    event_cache_ttl_seconds: int = 86400
    event_cache_max_events: int = 500


def get_persistence_config() -> PersistenceConfig:
    load_environment()
    return PersistenceConfig(
        job_db_path=os.getenv("VIDEO_REVIEW_JOB_DB", "local_data/review_jobs.sqlite3"),
        checkpoint_backend=os.getenv("VIDEO_REVIEW_CHECKPOINT_BACKEND", "sqlite").lower(),
        checkpoint_db_path=os.getenv(
            "VIDEO_REVIEW_CHECKPOINT_DB",
            "local_data/langgraph_checkpoints.sqlite3",
        ),
        event_cache_backend=os.getenv("VIDEO_REVIEW_EVENT_CACHE", "auto").lower(),
        redis_url=os.getenv("VIDEO_REVIEW_REDIS_URL", "redis://localhost:6379/0"),
        event_cache_ttl_seconds=int(os.getenv("VIDEO_REVIEW_EVENT_CACHE_TTL_SECONDS", "86400")),
        event_cache_max_events=int(os.getenv("VIDEO_REVIEW_EVENT_CACHE_MAX_EVENTS", "500")),
    )
