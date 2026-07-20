"""LangGraph workflow for the short-video review agent."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

# 导入analytics.py文件中自定义的数据分析模块
from video_review_agent.analytics import (
    analyze_comments, # 评论分析
    build_recommendations, # 构建优化建议
    infer_content_insights, # 推断内容洞察
    summarize_metrics, # 汇总核心指标
)
from video_review_agent.collectors import collect_video_data
from video_review_agent.llm import polish_report_with_llm
from video_review_agent.memory import (
    CreatorMemoryStore, # 创作者记忆存储库（基于Qdrant）
    build_experience_document, # 构建经验总结文档
    build_memory_query, # 构建记忆检索查询词
)
from video_review_agent.reporting import render_markdown_report
from video_review_agent.state import VideoReviewState


def build_graph():
    """构建并编译 LangGraph 状态图，定义agent执行的节点和边"""
    
    # 初始化状态图，指定全局状态的数据结构为 VideoReviewState
    graph = StateGraph(VideoReviewState)
    # 每添加一个节点代表一个具体的执行函数
    graph.add_node("retrieve_memory", retrieve_memory_node) # 检查历史记忆
    graph.add_node("collect_data", collect_data_node) # 采集视频数据
    graph.add_node("summarize_metrics", summarize_metrics_node) # 统计指标汇总
    graph.add_node("analyze_comments", analyze_comments_node) # 评论情感与内容分析
    graph.add_node("infer_content", infer_content_node) # 视频内容深度洞察
    graph.add_node("recommend", recommend_node) # 生成针对性建议
    graph.add_node("render_report", render_report_node) # 渲染markdown报告
    graph.add_node("store_memory", store_memory_node) # 将本次经验存入记忆库

    # 添加边，定义节点的执行顺序
    graph.add_edge(START, "retrieve_memory")
    graph.add_edge("retrieve_memory", "collect_data")
    graph.add_edge("collect_data", "summarize_metrics")
    graph.add_edge("summarize_metrics", "analyze_comments")
    graph.add_edge("analyze_comments", "infer_content")
    graph.add_edge("infer_content", "recommend")
    graph.add_edge("recommend", "render_report")
    graph.add_edge("render_report", "store_memory")
    graph.add_edge("store_memory", END)
    
    # 编译并返回构建好的图应用 
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
    """
    运行视频评估工作流的统一入口函数
    负责初始化初始状态并启动图的执行
    
    """
    app = build_graph()
    # 调用app.invoke传入初始状态数据（payload），图会按照定义的边自动流转
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

# ======== 下面是各个节点的具体实现 ========================
# 在langgraph中，节点函数返回的字典会自动与全局的 VideoReviewState 进行合并

def retrieve_memory_node(state: VideoReviewState) -> VideoReviewState:
    """节点1：从向量数据库中检索该创作者的历史偏好和经验"""
    if not state.get("memory_enabled", True):
        return {"historical_preferences": []}

    # 实例化记忆存储库（底层是 Qdrant 向量数据库）
    store = CreatorMemoryStore(persist_dir=state.get("memory_dir", "memory/qdrant"))
    try:
        memories = store.search_creator_preferences(
            creator_id=state.get("creator_id", "default_creator"),
            query=build_memory_query(state),
            limit=5,
        )
    finally:
        store.close()

    # 将检索到的记忆更新到全局状态中
    return {"historical_preferences": memories}


def collect_data_node(state: VideoReviewState) -> VideoReviewState:
    """节点2： 从真实平台或者本地 JSON获取视频数据 """
    raw_data = collect_video_data(
        video_id=state["video_id"],
        source_path=state.get("source_path", "data/sample_video_metrics.json"),
        days_after_publish=state.get("days_after_publish", 7),
        platform=state.get("platform", "json"),
        max_comments=state.get("max_comments", 50),
        top_liked_comments_limit=state.get("top_liked_comments_limit", 5),
    )
    # 将采集到的原生字典存入状态的raw_data字段
    return {"raw_data": raw_data}


def summarize_metrics_node(state: VideoReviewState) -> VideoReviewState:
    """节点3： 基于原始数据计算播放、点赞、转化率等核心指标"""
    return {"metrics_summary": summarize_metrics(state["raw_data"])}


def analyze_comments_node(state: VideoReviewState) -> VideoReviewState:
    """节点4： 分析评论区数据"""
    return {"comment_insights": analyze_comments(state["raw_data"])}


def infer_content_node(state: VideoReviewState) -> VideoReviewState:
    """节点5： 结合原始数据和评论洞察，推断视频内容本身的优缺点"""
    return {
        "content_insights": infer_content_insights(
            state["raw_data"],
            state["comment_insights"],
        )
    }


def recommend_node(state: VideoReviewState) -> VideoReviewState:
    """节点6： 基于前置的所有分析结果，生成可落地的优化建议"""
    return {
        "recommendations": build_recommendations(
            state["metrics_summary"],
            state["comment_insights"],
            state["content_insights"],
        )
    }


def render_report_node(state: VideoReviewState) -> VideoReviewState:
    """节点7： 将所有结构化数据拼装并渲染成 Markdown 格式的报告"""
    report = render_markdown_report(state)
    
    # 如果启用了大模型，则调用 LLM 对报告进行润色和口语化处理
    if state.get("use_llm"):
        report = polish_report_with_llm(report)
    return {"report": report}


def store_memory_node(state: VideoReviewState) -> VideoReviewState:
    """节点8： 将本次复盘总结的经验持久化写入向量数据库，供未来参考"""
    if not state.get("memory_enabled", True):
        return {}

    store = CreatorMemoryStore(persist_dir=state.get("memory_dir", "memory/qdrant"))
    try:
        # 将当前状态提炼成一条经验文档
        experience = build_experience_document(state)
        # 写入数据库，获取该记录的 ID
        experience_id = store.add_experience(experience)
    finally:
        store.close()
    return {"stored_experience_id": experience_id}


graph = build_graph()
