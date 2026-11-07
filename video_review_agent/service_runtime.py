"""In-process Flask API for review jobs and post-report feedback."""

from __future__ import annotations

import json
import queue
import re
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from video_review_agent.experience_store import ExperienceStore
from video_review_agent.workflow import build_graph


@dataclass
class ReviewJob:
    job_id: str
    request_payload: dict[str, Any]
    status: str = "queued"
    result: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[queue.Queue] = field(default_factory=list, repr=False)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def publish(self, event: dict[str, Any]) -> None:
        payload = {**event, "job_id": self.job_id}
        with self.lock:
            self.events.append(payload)
            if len(self.events) > 500:
                del self.events[:-500]
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


class ReviewJobManager:
    def __init__(self) -> None:
        self.jobs: dict[str, ReviewJob] = {}
        self.lock = threading.RLock()

    def start_review(self, payload: dict[str, Any]) -> ReviewJob:
        job = ReviewJob(job_id=str(uuid.uuid4()), request_payload=payload)
        with self.lock:
            self.jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job,), daemon=True, name=f"review-{job.job_id}").start()
        return job

    def _run(self, job: ReviewJob) -> None:
        job.status = "running"
        job.publish({"type": "run_started", "status": job.status})
        try:
            for event in build_graph().stream(job.request_payload, stream_mode="updates"):
                node, delta = next(iter(event.items()))
                if isinstance(delta, dict):
                    job.result.update(delta)
                job.publish({"type": "node_update", "node": node, "data": delta})
            job.status = "completed"
            job.publish({"type": "completed", "result": _public_result(job.result)})
        except Exception as exc:
            job.status = "failed"
            job.publish({"type": "error", "error": f"{type(exc).__name__}: {exc}"})


def create_app() -> Flask:
    root = Path(__file__).resolve().parent.parent
    app = Flask(__name__, template_folder=str(root / "templates"), static_folder=str(root / "static"))
    manager = ReviewJobManager()
    experiences = ExperienceStore()

    @app.get("/")
    def dashboard() -> str:
        return render_template("dashboard.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        return {"status": "ok", "job_store": "in-memory", "event_stream": "in-process SSE"}, 200

    @app.get("/api/hypotheses")
    def list_hypotheses() -> tuple[dict[str, Any], int]:
        creator_id = request.args.get("creator_id", "default_creator")
        return {"hypotheses": experiences.list_hypotheses(creator_id)}, 200

    @app.post("/api/reviews")
    def create_review() -> tuple[dict[str, Any], int]:
        payload = _normalize_payload(request.get_json(force=True) or {})
        requested = payload.get("selected_hypotheses", [])
        selected_ids = [item.get("id") for item in requested if isinstance(item, dict) and item.get("id")]
        payload["selected_hypotheses"] = experiences.get_hypotheses(payload["creator_id"], selected_ids)
        job = manager.start_review(payload)
        return {
            "job_id": job.job_id,
            "status": job.status,
            "events_url": f"/api/reviews/{job.job_id}/events",
            "result_url": f"/api/reviews/{job.job_id}",
            "feedback_url": f"/api/reviews/{job.job_id}/feedback",
        }, 202

    @app.get("/api/reviews/<job_id>")
    def get_review(job_id: str) -> tuple[dict[str, Any], int]:
        job = manager.jobs.get(job_id)
        if job is None:
            return {"error": "job not found"}, 404
        return {"job_id": job_id, "status": job.status, "result": _public_result(job.result)}, 200

    @app.get("/api/reviews/<job_id>/events")
    def stream_review_events(job_id: str) -> Response:
        job = manager.jobs.get(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        def event_stream() -> Iterable[str]:
            subscriber = job.add_subscriber()
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=10)
                        yield _format_sse(event)
                        if event.get("type") in {"completed", "error"}:
                            break
                    except queue.Empty:
                        yield ": heartbeat\n\n"
            finally:
                job.remove_subscriber(subscriber)

        return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

    @app.post("/api/reviews/<job_id>/feedback")
    def review_feedback(job_id: str) -> tuple[dict[str, Any], int]:
        job = manager.jobs.get(job_id)
        if job is None:
            return {"error": "job not found"}, 404
        payload = request.get_json(force=True) or {}
        if payload.get("satisfied") is True:
            if job.status != "completed":
                return {"error": "review must finish before confirmation"}, 409
            result = job.result
            if result.get("experience_id"):
                return {"status": "saved", "experience_id": result["experience_id"]}, 200
            experience_id = experiences.save_confirmed_review({
                "creator_id": job.request_payload.get("creator_id", "default_creator"),
                "user_question": job.request_payload.get("user_question", ""),
                "summary": result.get("summary", ""),
                "evidence": result.get("evidence", []),
                "hypotheses": result.get("hypotheses", []),
            })
            result["experience_id"] = experience_id
            for validation in result.get("followup_validations", []):
                hypothesis_id = validation.get("hypothesis_id")
                if hypothesis_id:
                    experiences.record_validation(
                        job.request_payload.get("creator_id", "default_creator"),
                        [hypothesis_id],
                        validation,
                    )
            return {"status": "saved", "experience_id": experience_id}, 200

        correction = str(payload.get("correction", "")).strip()
        if not correction:
            return {"error": "provide a correction or mark the report satisfied"}, 400
        rerun_payload = {
            **job.request_payload,
            "user_question": job.request_payload.get("user_question", "") + "\n用户纠偏：" + correction,
            "user_feedback": correction,
        }
        rerun = manager.start_review(rerun_payload)
        return {"job_id": rerun.job_id, "status": rerun.status, "events_url": f"/api/reviews/{rerun.job_id}/events"}, 202

    return app


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    raw = str(payload.get("video_url") or payload.get("video_id") or "").strip()
    platform = str(payload.get("platform", "auto")).lower()
    bvid = _extract_bvid(raw)
    av_match = re.search(r"av\d+", raw, re.IGNORECASE)
    if platform == "auto":
        platform = "bilibili" if bvid or raw else "json"
    video_id = bvid or (av_match.group(0) if av_match else raw) or "demo-video-001"
    return {
        "video_id": video_id,
        "platform": "json" if platform == "json" else "bilibili",
        "source_path": str(payload.get("source_path", "data/sample_video_metrics.json")),
        "user_question": str(payload.get("user_question", "请复盘这条视频的表现")),
        "creator_id": str(payload.get("creator_id", "default_creator")),
        "days_after_publish": int(payload.get("days_after_publish", 30)),
        "max_comments": int(payload.get("max_comments", 50)),
        "top_liked_comments_limit": int(payload.get("top_liked_comments_limit", 5)),
        "selected_hypotheses": payload.get("selected_hypotheses", []),
        "user_feedback": str(payload.get("user_feedback", "")),
    }


def _extract_bvid(value: str) -> str | None:
    match = re.search(r"BV[0-9A-Za-z]{10,}", value)
    if match:
        return match.group(0)
    query = parse_qs(urlparse(value).query)
    return (query.get("bvid") or [None])[0]


def _public_result(state: dict[str, Any]) -> dict[str, Any]:
    keys = ("report", "todos", "selected_metrics", "comment_insights", "comment_counts", "explanations", "hypotheses", "followup_validations", "evidence", "summary", "data_limitations", "observations", "historical_experiences")
    return {key: state[key] for key in keys if key in state}


def _format_sse(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
