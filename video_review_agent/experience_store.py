from __future__ import annotations

import json
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from video_review_agent.config import load_environment


class ExperienceStore:
    """Small local JSON store for user-confirmed review experience."""

    def __init__(self, path: str | None = None) -> None:
        load_environment()
        self.path = Path(path or os.getenv("VIDEO_REVIEW_EXPERIENCE_PATH", "local_data/experiences.json"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list_hypotheses(self, creator_id: str) -> list[dict[str, Any]]:
        records = self._read()
        return [
            {**hypothesis, "experience_id": record["id"]}
            for record in records
            if record.get("creator_id") == creator_id
            for hypothesis in record.get("hypotheses", [])
        ]

    def search(self, creator_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        scored = []
        for record in self._read():
            if record.get("creator_id") != creator_id:
                continue
            eligible = [
                hypothesis for hypothesis in record.get("hypotheses", [])
                if hypothesis.get("confidence") == "high"
                or sum(item.get("status") == "supported" for item in hypothesis.get("validations", [])) >= 2
            ]
            if not eligible:
                continue
            text = " ".join(
                [record.get("question", ""), record.get("summary", "")]
                + [item.get("statement", "") for item in eligible]
            )
            overlap = len(query_tokens & _tokens(text))
            if overlap:
                scored.append((overlap, {**record, "hypotheses": eligible}))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [record for _, record in scored[:limit]]

    def get_hypotheses(self, creator_id: str, ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(ids)
        return [
            {**hypothesis, "experience_id": record["id"]}
            for record in self._read()
            if record.get("creator_id") == creator_id
            for hypothesis in record.get("hypotheses", [])
            if hypothesis.get("id") in wanted
        ]

    def save_confirmed_review(self, review: dict[str, Any]) -> str:
        record = {
            "id": str(uuid.uuid4()),
            "creator_id": review.get("creator_id", "default_creator"),
            "question": review.get("user_question", ""),
            "summary": review.get("summary", ""),
            "evidence": review.get("evidence", []),
            "hypotheses": review.get("hypotheses", []),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        for hypothesis in record["hypotheses"]:
            hypothesis.setdefault("id", str(uuid.uuid4()))
            hypothesis.setdefault("status", "unverified")
            hypothesis.setdefault("validations", [])
        with self._lock:
            records = self._read()
            records.append(record)
            self._write(records)
        return record["id"]

    def record_validation(self, creator_id: str, hypothesis_ids: list[str], validation: dict[str, Any]) -> None:
        wanted = set(hypothesis_ids)
        with self._lock:
            records = self._read()
            changed = False
            for record in records:
                if record.get("creator_id") != creator_id:
                    continue
                for hypothesis in record.get("hypotheses", []):
                    if hypothesis.get("id") in wanted:
                        hypothesis.setdefault("validations", []).append(validation)
                        changed = True
            if changed:
                self._write(records)

    def _read(self) -> list[dict[str, Any]]:
        with self._lock:
            if not self.path.exists():
                return []
            try:
                value = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return value if isinstance(value, list) else []

    def _write(self, records: list[dict[str, Any]]) -> None:
        self.path.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def _tokens(value: str) -> set[str]:
    terms = re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z0-9_+-]{2,}", value.lower())
    tokens = set(terms)
    for term in terms:
        if re.fullmatch(r"[\u4e00-\u9fff]+", term) and len(term) > 2:
            tokens.update(term[index:index + 2] for index in range(len(term) - 1))
    return tokens
