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
