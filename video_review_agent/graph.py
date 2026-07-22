"""LangGraph workflow for the short-video review agent."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from video_review_agent.analytics import (
    analyze_comments,
    build_recommendations,
    infer_content_insights,
    summarize_metrics,
)
from video_review_agent.collectors import collect_video_data
from video_review_agent.llm import polish_report_with_llm
from video_review_agent.memory import (
    CreatorMemoryStore,
    build_experience_document,
    build_memory_query,
    format_memories_for_report,
)
from video_review_agent.reporting import render_markdown_report
from video_review_agent.state import VideoReviewState


DEFAULT_CHECKPOINTER = MemorySaver()


def build_graph(checkpointer: MemorySaver | None = None):
    """Build and compile the LangGraph workflow.

    A checkpointer is required for human-in-the-loop interrupt/resume. The default
    MemorySaver is process-local, which fits a running backend service or tests.
    """

    graph = StateGraph(VideoReviewState)
    graph.add_node("retrieve_memory", retrieve_memory_node)
    graph.add_node("collect_data", collect_data_node)
    graph.add_node("summarize_metrics", summarize_metrics_node)
    graph.add_node("analyze_comments", analyze_comments_node)
    graph.add_node("infer_content", infer_content_node)
    graph.add_node("recommend", recommend_node)
    graph.add_node("plan_review", plan_review_node)
    graph.add_node("render_report", render_report_node)
    graph.add_node("store_memory", store_memory_node)

    graph.add_edge(START, "retrieve_memory")
    graph.add_edge("retrieve_memory", "collect_data")
    graph.add_edge("collect_data", "summarize_metrics")
    graph.add_edge("summarize_metrics", "analyze_comments")
    graph.add_edge("analyze_comments", "infer_content")
    graph.add_edge("infer_content", "recommend")
    graph.add_edge("recommend", "plan_review")
    graph.add_conditional_edges(
        "plan_review",
        route_after_plan_review,
        {
            "render_report": "render_report",
            "end": END,
        },
    )
    graph.add_edge("render_report", "store_memory")
    graph.add_edge("store_memory", END)
    return graph.compile(checkpointer=checkpointer or DEFAULT_CHECKPOINTER)


def run_video_review(
    video_id: str,
    source_path: str = "data/sample_video_metrics.json",
    days_after_publish: int = 7,
    platform: str = "json",
    max_comments: int = 50,
    top_liked_comments_limit: int = 5,
    creator_id: str = "default_creator",
    memory_dir: str = "memory/qdrant",
    memory_enabled: bool = True,
    use_llm: bool = False,
    require_plan_approval: bool = False,
    thread_id: str | None = None,
) -> VideoReviewState:
    """Run the video review workflow.

    When ``require_plan_approval`` is true, the graph interrupts after generating
    recommendations. Resume with ``resume_video_review`` and the same thread id.
    """

    checkpoint_thread_id = thread_id or f"video-review-{uuid4()}"
    app = build_graph()
    return app.invoke(
        {
            "video_id": video_id,
            "creator_id": creator_id,
            "source_path": source_path,
            "platform": platform,
            "days_after_publish": days_after_publish,
            "max_comments": max_comments,
            "top_liked_comments_limit": top_liked_comments_limit,
            "memory_dir": memory_dir,
            "memory_enabled": memory_enabled,
            "use_llm": use_llm,
            "require_plan_approval": require_plan_approval,
            "checkpoint_thread_id": checkpoint_thread_id,
            "errors": [],
        },
        config=build_thread_config(checkpoint_thread_id),
    )


def resume_video_review(
    thread_id: str,
    resume_payload: dict[str, Any] | bool | str | None = None,
) -> VideoReviewState:
    """Resume an interrupted graph execution with user approval or edits.

    Suggested payload:
        {"approved": True, "recommendations": ["..."], "review_notes": "..."}
    """

    app = build_graph()
    return app.invoke(
        Command(resume=resume_payload if resume_payload is not None else {"approved": True}),
        config=build_thread_config(thread_id),
    )


def build_thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    return {"configurable": {"thread_id": thread_id}}


def retrieve_memory_node(state: VideoReviewState) -> VideoReviewState:
    if not state.get("memory_enabled", True):
        return {"historical_preferences": []}

    store = CreatorMemoryStore(persist_dir=state.get("memory_dir", "memory/qdrant"))
    try:
        memories = store.search_creator_preferences(
            creator_id=state.get("creator_id", "default_creator"),
            query=build_memory_query(state),
            limit=5,
        )
    finally:
        store.close()
    return {"historical_preferences": memories}


def collect_data_node(state: VideoReviewState) -> VideoReviewState:
    raw_data = collect_video_data(
        video_id=state["video_id"],
        source_path=state.get("source_path", "data/sample_video_metrics.json"),
        days_after_publish=state.get("days_after_publish", 7),
        platform=state.get("platform", "json"),
        max_comments=state.get("max_comments", 50),
        top_liked_comments_limit=state.get("top_liked_comments_limit", 5),
    )
    return {"raw_data": raw_data}


def summarize_metrics_node(state: VideoReviewState) -> VideoReviewState:
    return {"metrics_summary": summarize_metrics(state["raw_data"])}


def analyze_comments_node(state: VideoReviewState) -> VideoReviewState:
    return {"comment_insights": analyze_comments(state["raw_data"])}


def infer_content_node(state: VideoReviewState) -> VideoReviewState:
    return {
        "content_insights": infer_content_insights(
            state["raw_data"],
            state["comment_insights"],
        )
    }


def recommend_node(state: VideoReviewState) -> VideoReviewState:
    return {
        "recommendations": build_recommendations(
            state["metrics_summary"],
            state["comment_insights"],
            state["content_insights"],
        )
    }


def plan_review_node(state: VideoReviewState) -> VideoReviewState:
    plan = build_review_plan(state)
    if not state.get("require_plan_approval", False):
        return {"execution_plan": plan, "plan_approved": True}

    resume_value = interrupt(plan)
    return apply_plan_review_response(state, plan, resume_value)


def route_after_plan_review(state: VideoReviewState) -> str:
    return "render_report" if state.get("plan_approved", True) else "end"


def render_report_node(state: VideoReviewState) -> VideoReviewState:
    report = render_markdown_report(state)
    if state.get("use_llm"):
        report = polish_report_with_llm(report)
    return {"report": report}


def store_memory_node(state: VideoReviewState) -> VideoReviewState:
    if not state.get("memory_enabled", True):
        return {}

    store = CreatorMemoryStore(persist_dir=state.get("memory_dir", "memory/qdrant"))
    try:
        experience = build_experience_document(state)
        experience_id = store.add_experience(experience)
    finally:
        store.close()
    return {"stored_experience_id": experience_id}


def build_review_plan(state: VideoReviewState) -> dict[str, Any]:
    raw_data = state.get("raw_data", {})
    comments = state.get("comment_insights", {})
    content = state.get("content_insights", {})
    return {
        "status": "awaiting_user_approval",
        "thread_id": state.get("checkpoint_thread_id", ""),
        "creator_id": state.get("creator_id", "default_creator"),
        "video_id": raw_data.get("video_id", state.get("video_id", "")),
        "title": raw_data.get("title", ""),
        "metrics_summary": state.get("metrics_summary", {}),
        "comment_summary": {
            "sentiment": comments.get("sentiment", {}),
            "hot_keywords": comments.get("hot_keywords", []),
            "questions": comments.get("questions", []),
        },
        "content_insights": content,
        "historical_preferences": format_memories_for_report(
            state.get("historical_preferences", [])
        ),
        "recommendations": state.get("recommendations", []),
        "resume_payload_example": {
            "approved": True,
            "recommendations": state.get("recommendations", []),
            "review_notes": "用户确认或修改 Plan 后的备注",
        },
    }


def apply_plan_review_response(
    state: VideoReviewState,
    plan: dict[str, Any],
    resume_value: dict[str, Any] | bool | str | None,
) -> VideoReviewState:
    updates: VideoReviewState = {"execution_plan": plan, "plan_approved": True}

    if isinstance(resume_value, bool):
        updates["plan_approved"] = resume_value
    elif isinstance(resume_value, str):
        updates["plan_review_notes"] = resume_value
    elif isinstance(resume_value, dict):
        approved = bool(resume_value.get("approved", True))
        updates["plan_approved"] = approved
        if isinstance(resume_value.get("recommendations"), list):
            updates["recommendations"] = [str(item) for item in resume_value["recommendations"]]
        if isinstance(resume_value.get("execution_plan"), dict):
            updates["execution_plan"] = resume_value["execution_plan"]
        elif isinstance(resume_value.get("plan"), dict):
            updates["execution_plan"] = resume_value["plan"]
        if resume_value.get("review_notes"):
            updates["plan_review_notes"] = str(resume_value["review_notes"])
    elif resume_value is None:
        updates["plan_approved"] = True

    if not updates.get("plan_approved", True):
        updates["errors"] = state.get("errors", []) + ["Plan was rejected by the user."]

    return updates


graph = build_graph()
