"""Flask service for productizing the review workflow.
将视频评估工作流（基于langgraph）产品化的 Flask服务端代码
"""

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

# 定义任务的终止状态和等待状态
TERMINAL_STATUSES = {"completed", "rejected", "failed"}
WAITING_STATUSES = {"awaiting_approval"}


@dataclass
class ReviewJob:
    """
    任务数据类：用于追踪每一个后台评估任务的状态、事件流和最终结果
    """
    job_id: str
    thread_id: str # ；langgraph 用于维持对话上下文的线程 ID
    request_payload: dict[str, Any]
    status: str = "queued"
    events: list[dict[str, Any]] = field(default_factory=list) # 记录任务产生的所有事件流
    result: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # 订阅者队列：每一个连接到 SSE 接口的客户端都会持有一个 Queue
    # 任务产生新事件时，会广播给所有订阅者
    subscribers: list[queue.Queue] = field(default_factory=list, repr=False)

    # 可重入锁（Rlock）：保证多线程环境下对该任务状态修改的线程安全
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    def publish(self, event: dict[str, Any]) -> None:
        """发布一个事件到当前任务的所有订阅者（通常是前端SSE监听器）"""
        payload = _jsonable(event)
        payload.setdefault("job_id", self.job_id)
        payload.setdefault("thread_id", self.thread_id)
        payload.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        with self.lock: # 加锁，防止并发写入冲突
            self.events.append(payload)
            self.updated_at = payload["timestamp"]
            # 将事件放入每一个订阅者的消息队列中
            for subscriber in list(self.subscribers):
                subscriber.put(payload)

    def add_subscriber(self) -> queue.Queue:
        """新增一个订阅者（前端发起SSE连接时调用），返回一个消息列表"""
        subscriber: queue.Queue = queue.Queue()
        with self.lock:
            # 补发历史事件，让新连上来的客户端能看到之前的进度
            for event in self.events:
                subscriber.put(event)
            self.subscribers.append(subscriber)
        return subscriber

    def remove_subscriber(self, subscriber: queue.Queue) -> None:
        """移除订阅者（客户端断开连接时调用）"""
        with self.lock:
            if subscriber in self.subscribers:
                self.subscribers.remove(subscriber)

    def snapshot(self) -> dict[str, Any]:
        """获取当前任务状态的快照（用于普通的GET API 请求）"""
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
    """全局后台状态管理器：负责创建、存储和恢复任务"""
    def __init__(self) -> None:
        self._jobs: dict[str, ReviewJob] = {} # 内存字典存储所有任务
        self._lock = threading.RLock() # 保护任务字典的全局锁

    def create_job(self, request_payload: dict[str, Any]) -> ReviewJob:
        """创建一个全新的任务对象并存入字典"""
        job_id = str(uuid.uuid4())
        thread_id = request_payload.get("thread_id") or job_id
        payload = dict(request_payload)
        payload["thread_id"] = thread_id
        job = ReviewJob(job_id=job_id, thread_id=thread_id, request_payload=payload)
        with self._lock:
            self._jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> ReviewJob | None:
        """通过ID获取任务"""
        with self._lock:
            return self._jobs.get(job_id)

    def start_review(self, request_payload: dict[str, Any]) -> ReviewJob:
        """后台任务核心：启动一个新的评估任务"""
        job = self.create_job(request_payload)

        # 开启一个新的守护线程，避免阻塞 Flask 的主线程
        thread = threading.Thread(
            target=self._run_initial,
            args=(job,),
            daemon=True,
            name=f"review-{job.job_id}",
        )
        thread.start()
        return job

    def resume_review(self, job_id: str, resume_payload: dict[str, Any] | bool | str | None) -> ReviewJob:
        """
        恢复处于挂起（等待人工审批）状态的任务
        """

        job = self.get_job(job_id)
        if job is None:
            raise KeyError(f"Job not found: {job_id}")
        if job.status not in WAITING_STATUSES:
            raise ValueError(f"Job {job_id} is not waiting for approval.")

        # 同样开启新线程去恢复执行 langgraph 图
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
        """执行 langgraph 工作流的实际引擎函数（运行在后台线程中）"""
        app = build_graph()
        job.status = "running"
        job.publish({"type": "run_started" if initial else "run_resumed", "status": job.status})
        try:
            # 区分是首次运行还是带有审批数据的恢复运行
            if initial:
                initial_state = _build_initial_state(job.request_payload)
                # stream 模式：工作流每跑完一个节点，就会 yield一次进度
                stream = app.stream(
                    initial_state,
                    config=build_thread_config(job.thread_id),
                    stream_mode="updates",
                )
            else:
                # 触发恢复执行命令，通常携带用户人工审核之后的指令
                stream = app.stream(
                    Command(resume=resume_payload if resume_payload is not None else {"approved": True}),
                    config=build_thread_config(job.thread_id),
                    stream_mode="updates",
                )

            for event in stream:
                # 捕获断点：流程跑到了需要人工确认的地方停下了
                if "__interrupt__" in event:
                    plan = event["__interrupt__"][0].value
                    job.plan = _jsonable(plan)
                    job.status = "awaiting_approval" # 状态变更为等待审批
                    job.publish({"type": "interrupted", "node": "plan_review", "plan": job.plan})
                    return # 线程结束，等待后续用户调 resume 接口唤醒

                # 解析正常节点的输出
                node_name, delta = next(iter(event.items()))
                delta_json = _jsonable(delta) or {}

                # 将节点产生的新状态合并到任务全局结果中
                if isinstance(delta_json, dict):
                    job.result = _merge_dicts(job.result, delta_json)
                event_type = "node_update"

                # 针对分析仪表盘节点的特殊处理
                if (
                    node_name == "data_analyst"
                    and isinstance(delta_json, dict)
                    and "dashboard_data" in delta_json
                ):
                    event_type = "dashboard_update"

                # 每跑完一个节点，就将事件推送给前端 SSE 监听器
                job.publish(
                    {
                        "type": event_type,
                        "node": node_name,
                        "data": delta_json,
                    }
                )

            # 判断流程是否因为计划被拒绝而终止
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
    """Flask 应用工厂和函数"""
    root = Path(__file__).resolve().parent.parent
    app = Flask(
        __name__,
        template_folder=str(root / "templates"),
        static_folder=str(root / "static"),
    )
    manager = ReviewJobManager()

    # 下面是具体的 REST API 路由映射

    @app.get("/")
    def dashboard() -> str:
        return render_template("dashboard.html")

    @app.get("/api/health")
    def health() -> tuple[dict[str, str], int]:
        """健康检查接口，常用于 K8s 或者网关探活"""
        return {"status": "ok"}, 200

    @app.post("/api/reviews")
    def create_review() -> tuple[dict[str, Any], int]:
        """创建评估任务 API"""
        payload = request.get_json(force=True, silent=False) or {}
        normalized = _normalize_request_payload(payload)

        # 调用manager 启动后台线程，立刻返回 202状态码，不阻塞等待
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
        """获取特定任务状态的 API"""
        job = manager.get_job(job_id)
        if job is None:
            return {"error": "job not found"}, 404
        return job.snapshot(), 200

    @app.post("/api/reviews/<job_id>/resume")
    def resume_review(job_id: str) -> tuple[dict[str, Any], int]:
        """人工审批后，唤醒任务继续执行的API"""
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
        """SSE核心：提供基于 SSE的事件流接口。前端通过 EventSource 订阅此接口。服务器将源源不断推送进度"""
        job = manager.get_job(job_id)
        if job is None:
            return jsonify({"error": "job not found"}), 404

        def event_stream() -> Iterable[str]:
            # 生成一个专属的消费者队列
            subscriber = job.add_subscriber()
            try:
                while True:
                    try:
                        event = subscriber.get(timeout=10)
                        # 将事件包装成SSE协议规定的文本格式并 yield 推送
                        yield _format_sse(event.get("type", "message"), event)
                        if event.get("type") in TERMINAL_STATUSES:
                            break
                    except queue.Empty:
                        # 每隔10s发一个心跳包，防止代理服务器因长期静默断开长连接
                        yield _format_sse("heartbeat", {"type": "heartbeat", "job_id": job.job_id})
            finally:
                # 无论前端主动断开还是发生异常，都清理掉订阅者，防止内存泄露
                job.remove_subscriber(subscriber)

        return Response(stream_with_context(event_stream()), mimetype="text/event-stream")

    return app


def _normalize_request_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """数据清洗与辅助函数"""
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
    """从输入的 URL 或原始字符串中智能提取目标平台和视频 ID（支持 B站）。"""
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
    """使用正则表达式或 URL 参数解析来寻找 B 站视频 BV 号。"""
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
    """构建图执行的初始状态字典。"""
    state = dict(request_payload)
    state.setdefault("errors", [])
    return state


def _merge_dicts(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    """深度合并两个字典（用于合并 LangGraph 节点的增量输出到最终结果）。"""
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
