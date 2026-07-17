"""Optional LLM polishing for final reports."""

from __future__ import annotations

from video_review_agent.config import get_llm_config


def polish_report_with_llm(report: str) -> str:
    """Polish a deterministic report when a supported LLM is configured.

    The agent remains useful without an LLM. This function is deliberately isolated
    so platform data analysis is testable and secrets stay in environment variables.
    """

    config = get_llm_config()
    if not config.enabled:
        return report

    try:
        from langchain.chat_models import init_chat_model
        from langchain_core.messages import HumanMessage, SystemMessage
    except Exception:
        return report

    llm = init_chat_model(model=config.model, model_provider=config.provider)
    response = llm.invoke(
        [
            SystemMessage(
                content=(
                    "你是短视频内容复盘助手。请在不改变事实数据的前提下，"
                    "把报告润色得更适合创作者阅读，保持 Markdown 结构。"
                )
            ),
            HumanMessage(content=report),
        ]
    )
    return str(response.content)
