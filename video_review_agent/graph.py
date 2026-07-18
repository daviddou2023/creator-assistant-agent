"""LangGraph workflow for the short-video review agent."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

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
)
from video_review_agent.reporting import render_markdown_report
from video_review_agent.state import VideoReviewState


def build_graph():
    graph = StateGraph(VideoReviewState)
    graph.add_node("retrieve_memory", retrieve_memory_node)
    graph.add_node("collect_data", collect_data_node)
    graph.add_node("summarize_metrics", summarize_metrics_node)
    graph.add_node("analyze_comments", analyze_comments_node)
    graph.add_node("infer_content", infer_content_node)
    graph.add_node("recommend", recommend_node)
    graph.add_node("render_report", render_report_node)
    graph.add_node("store_memory", store_memory_node)

    graph.add_edge(START, "retrieve_memory")
    graph.add_edge("retrieve_memory", "collect_data")
    graph.add_edge("collect_data", "summarize_metrics")
    graph.add_edge("summarize_metrics", "analyze_comments")
    graph.add_edge("analyze_comments", "infer_content")
    graph.add_edge("infer_content", "recommend")
    graph.add_edge("recommend", "render_report")
    graph.add_edge("render_report", "store_memory")
    graph.add_edge("store_memory", END)
    return graph.compile()


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
) -> VideoReviewState:
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
            "errors": [],
        }
    )


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


graph = build_graph()
