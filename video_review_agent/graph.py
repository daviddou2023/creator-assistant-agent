"""LangGraph public entry point for the evidence-driven review workflow."""

from video_review_agent.workflow import build_graph, run_video_review

graph = build_graph()
