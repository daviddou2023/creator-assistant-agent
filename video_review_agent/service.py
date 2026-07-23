"""Flask service for productizing the review workflow."""

from __future__ import annotations

import json
import queue
import re
import threading
import traceback
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from langgraph.types import Command

from video_review_agent.graph import build_graph, build_thread_config


TERMINAL_STATUSES = {"completed", "rejected", "failed"}
WAITING_STATUSES = {"awaiting_approval"}


@dataclass
class ReviewJob:
    job_id: str
    thread_id: str
    request_payload: dict[str, Any]
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list)
    result: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    subscribers: list[queue.Queue] = field(default_factory=list, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def publish(self, event: dict[str, Any]) -> None:
        payload = _jsonable(event)
        payload.setdefault("job_id", self.job_id)
        payload.setdefault("thread_id", self.thread_id)
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        with self.lock:
            self.events.append(payload)
            self.updated_at = payload["timestamp"]
            for subscriber in list(self.subscribers):
                subscriber.put(payload)

    def add_subscriber(self) -> queue.Queue:
        subscriber: queue.Queue = queue.Queue()
        with self.lock:
            for event in self.events:
                subscriber.put(event)
            self.subscribers.append(subscriber)
        return subscriber

    def remove_subscriber(self, subscriber: queue.Queue) -> None:
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "job_id": self.job_id,
                "thread_id": self.thread_id,
                "status": self.status,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "request": _jsonable(self.request_payload),
                "plan": _jsonable(self.plan),
                "result": _public_result(self.result),
                "error": self.error,
                "last_event": self.events[-1] if self.events else None,
            }


class ReviewJobManager:
    def __init__(self) -> None:
        self._jobs: dict[str, ReviewJob] = {}
        self._lock = threading.RLock()

    def create_job(self, request_payload: dict[str, Any]) -> ReviewJob:
        job_id = str(uuid.uuid4())
        thread_id = request_payload.get("thread_id") or job_id
        payload = dict(request_payload)
        payload["thread_id"] = thread_id
        job = ReviewJob(job_id=job_id, thread_id=thread_id, request_payload=payload)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> ReviewJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def start_review(self, request_payload: dict[str, Any]) -> ReviewJob:
        job = self.create_job(request_payload)
        thread = threading.Thread(
            target=self._run_initial,
            args=(job,),
            daemon=True,
            name=f"review-{job.job_id}",
        )
        thread.start()
        return job

    def resume_review(self, job_id: str, resume_payload: dict[str, Any] | bool | str | None) -> ReviewJob:
        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job.status not in WAITING_STATUSES:
            raise ValueError(f"Job {job_id} is not waiting for approval.")

        thread = threading.Thread(
            target=self._run_resume,
            args=(job, resume_payload),
            daemon=True,
            name=f"resume-{job.job_id}",
        )
        thread.start()
        return job

    def _run_initial(self, job: ReviewJob) -> None:
        self._run_graph(job, initial=True)

    def _run_resume(self, job: ReviewJob, resume_payload: dict[str, Any] | bool | str | None) -> None:
        job.publish({"type": "resume_started", "payload": _jsonable(resume_payload)})
        self._run_graph(job, initial=False, resume_payload=resume_payload)

    def _run_graph(
        self,
        job: ReviewJob,
        *,
        initial: bool,
        resume_payload: dict[str, Any] | bool | str | None = None,
    ) -> None:
        app = build_graph()
        job.status = "running"
        job.publish({"type": "run_started" if initial else "run_resumed", "status": job.status})
        try:
            if initial:
                initial_state = _build_initial_state(job.request_payload)
                stream = app.stream(
                    initial_state,
                    config=build_thread_config(job.thread_id),
                    stream_mode="updates",
                )
            else:
                stream = app.stream(
                    Command(resume=resume_payload if resume_payload is not None else {"approved": True}),
                    config=build_thread_config(job.thread_id),
                    stream_mode="updates",
                )

            for event in stream:
                if "__interrupt__" in event:
                    plan = event["__interrupt__"][0].value
                    job.plan = _jsonable(plan)
                    job.status = "awaiting_approval"
                    job.publish({"type": "interrupted", "node": "plan_review", "plan": job.plan})
                    return

                node_name, delta = next(iter(event.items()))
                delta_json = _jsonable(delta) or {}
                if isinstance(delta_json, dict):
                    job.result = _merge_dicts(job.result, delta_json)
                event_type = "node_update"
                if (
                    node_name == "data_analyst"
                    and isinstance(delta_json, dict)
                    and "dashboard_data" in delta_json
                ):
                    event_type = "dashboard_update"
                job.publish(
                    {
                        "type": event_type,
                        "node": node_name,
                        "data": delta_json,
                    }
                )

            if job.result.get("plan_approved", True) is False:
                job.status = "rejected"
                job.publish({"type": "rejected", "result": _public_result(job.result)})
                return

            job.status = "completed"
            job.publish({"type": "completed", "result": _public_result(job.result)})
        except Exception as exc:  # pragma: no cover - service safeguard
            job.status = "failed"
            job.error = "".join(traceback.format_exception(exc))
            job.publish({"type": "error", "error": job.error})


def create_app() -> Flask:
    root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    manager = ReviewJobManager()

    @app.get("/")
    def dashboard() -> str:
        return render_template("dashboard.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok"}, 200

    @app.post("/api/reviews")
    def create_review() -> tuple[dict[str, Any], int]:
        payload = request.get_json(force=True, silent=False) or {}
        normalized = _normalize_request_payload(payload)
        job = manager.start_review(normalized)
        response = {
            "job_id": job.job_id,
            "thread_id": job.thread_id,
            "status": job.status,
            "events_url": f"/api/reviews/{job.job_id}/events",
            "result_url": f"/api/reviews/{job.job_id}",
            "resume_url": f"/api/reviews/{job.job_id}/resume",
        }
        return response, 202

    @app.get("/api/reviews/<job_id>")
    def get_review(job_id: str) -> tuple[dict[str, Any], int]:
        job = manager.get_job(job_id)
        if job is None:
            return {"error": "job not found"}, 404
        return job.snapshot(), 200

    @app.post("/api/reviews/<job_id>/resume")
    def resume_review(job_id: str) -> tuple[dict[str, Any], int]:
        payload = request.get_json(force=True, silent=False) or {}
        resume_payload = payload.get("resume_payload", payload)
        try:
            job = manager.resume_review(job_id, resume_payload)
        except KeyError:
            return {"error": "job not found"}, 404
        except ValueError as exc:
            return {"error": str(exc)}, 409
        return {"job_id": job.job_id, "thread_id": job.thread_id, "status": job.status}, 202

    @app.get("/api/reviews/<job_id>/events")
    def stream_review_events(job_id: str) -> Response:
        job = manager.get_job(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        def event_stream() -> Iterable[str]:
            subscriber = job.add_subscriber()
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=10)
                        yield _format_sse(event.get("type", "message"), event)
                        if event.get("type") in TERMINAL_STATUSES:
                            break
                    except queue.Empty:
                        yield _format_sse("heartbeat", {"type": "heartbeat", "job_id": job.job_id})
            finally:
                job.remove_subscriber(subscriber)

        return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

    return app


def _normalize_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    video_url = str(payload.get("video_url", "")).strip()
    video_id = str(payload.get("video_id", "")).strip()
    platform = str(payload.get("platform", "auto")).strip().lower() or "auto"

    resolved_platform, resolved_video_id = _resolve_video_target(video_url or video_id, platform)

    return {
        "video_url": video_url,
        "video_id": resolved_video_id,
        "creator_id": str(payload.get("creator_id", "default_creator")),
        "source_path": str(payload.get("source_path", "data/sample_video_metrics.json")),
        "platform": resolved_platform,
        "days_after_publish": int(payload.get("days_after_publish", 7)),
        "max_comments": int(payload.get("max_comments", 50)),
        "top_liked_comments_limit": int(payload.get("top_liked_comments_limit", 5)),
        "memory_dir": str(payload.get("memory_dir", "memory/qdrant")),
        "memory_enabled": bool(payload.get("memory_enabled", False)),
        "use_llm": bool(payload.get("use_llm", False)),
        "require_plan_approval": bool(payload.get("require_plan_approval", True)),
        "thread_id": str(payload.get("thread_id", "")).strip() or None,
    }


def _resolve_video_target(raw_input: str, platform: str) -> tuple[str, str]:
    if platform == "json":
        return "json", raw_input or "demo-video-001"

    detected_bvid = _extract_bvid(raw_input)
    if detected_bvid:
        return "bilibili", detected_bvid

    av_match = re.search(r"av(\d+)", raw_input, re.IGNORECASE)
    if av_match:
        return "bilibili", f"av{av_match.group(1)}"

    if platform == "auto":
        return ("bilibili", raw_input) if raw_input else ("json", "demo-video-001")

    return platform, raw_input or "demo-video-001"


def _extract_bvid(text: str) -> str | None:
    match = re.search(r"(BV[0-9A-Za-z]{10,})", text)
    if match:
        return match.group(1)

    parsed = urlparse(text)
    if parsed.query:
        params = parse_qs(parsed.query)
        bvid = params.get("bvid", [])
        if bvid:
            return bvid[0]

    return None


def _build_initial_state(request_payload: dict[str, Any]) -> dict[str, Any]:
    state = dict(request_payload)
    state.setdefault("errors", [])
    return state


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_dicts(merged[key], value)
        else:
            merged[key] = value
    return merged


def _public_result(state: dict[str, Any]) -> dict[str, Any]:
    keys = [
        "video_id",
        "creator_id",
        "platform",
        "report",
        "execution_plan",
        "plan_approved",
        "plan_review_notes",
        "dashboard_data",
        "metrics_summary",
        "comment_insights",
        "content_insights",
        "recommendations",
        "historical_preferences",
        "stored_experience_id",
        "errors",
    ]
    return {key: _jsonable(state.get(key)) for key in keys if key in state}


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _jsonable(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return [_jsonable(item) for item in sorted(value, key=str)]
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value") and hasattr(value, "id"):
        return {"value": _jsonable(getattr(value, "value", None)), "id": str(getattr(value, "id", ""))}
    return value


def _format_sse(event_name: str, payload: dict[str, Any]) -> str:
    return f"event: {event_name}\ndata: {json.dumps(_jsonable(payload), ensure_ascii=False)}\n\n"
