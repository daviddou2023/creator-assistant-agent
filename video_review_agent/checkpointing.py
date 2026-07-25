"""LangGraph checkpointer factories."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from video_review_agent.config import get_persistence_config


_DEFAULT_CHECKPOINTER: Any | None = None
_DEFAULT_CHECKPOINTER_LOCK = threading.RLock()
_SQLITE_CONNECTIONS: list[sqlite3.Connection] = []


def get_default_checkpointer() -> Any:
    """Return a process-wide LangGraph checkpointer.

    If ``langgraph-checkpoint-sqlite`` is installed, the default backend stores
    checkpoints in SQLite. Without that optional dependency, local runs fall back
    to MemorySaver while the requirements file still documents the intended
    production dependency.
    """

    global _DEFAULT_CHECKPOINTER
    with _DEFAULT_CHECKPOINTER_LOCK:
        if _DEFAULT_CHECKPOINTER is None:
            _DEFAULT_CHECKPOINTER = build_configured_checkpointer()
        return _DEFAULT_CHECKPOINTER


def build_configured_checkpointer() -> Any:
    config = get_persistence_config()
    if config.checkpoint_backend == "memory":
        return MemorySaver()
    if config.checkpoint_backend != "sqlite":
        raise ValueError(f"Unsupported checkpoint backend: {config.checkpoint_backend}")
    return build_sqlite_checkpointer(config.checkpoint_db_path)


def build_sqlite_checkpointer(db_path: str) -> Any:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError:
        return MemorySaver()

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    _SQLITE_CONNECTIONS.append(conn)
    saver = SqliteSaver(conn)
    setup = getattr(saver, "setup", None)
    if callable(setup):
        setup()
    return saver
