"""Creator memory backed by a local Qdrant vector database."""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_MEMORY_DIR = "memory/qdrant"
DEFAULT_COLLECTION = "creator_review_experiences"


class HashEmbeddingFunction:
    """为本地存储设计的小型、确定性哈希嵌入（Embedding）函数。

    它的存在是为了让本地开发和自动化测试能够独立运行，无需消耗付费的 API 额度。
    它不能替代生产环境下的真实语义嵌入模型（如 OpenAI 或 BGE 模型），
    但它通过词频和哈希散列，能为 Agent 提供一个稳定且勉强够用的文本向量表示，用于基础的相似度检索。
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def name(self) -> str:
        return "video-review-hash-embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        # 对文本进行分词
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        # 计算向量的L2范数
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        # 归一化处理
        return [round(value / norm, 6) for value in vector]


class CreatorMemoryStore:
    """创作者记忆存储库，封装了对 Qdrant向量数据库的增删改查操作"""
    def __init__(
        self,
        persist_dir: str = DEFAULT_MEMORY_DIR,
        collection_name: str = DEFAULT_COLLECTION,
    ) -> None:
        
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.models import Distance, VectorParams
        except ImportError as exc:
            raise RuntimeError("Install qdrant-client to use creator memory: pip install qdrant-client") from exc

        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        self.embedding_function = HashEmbeddingFunction()
        self.collection_name = collection_name
        self.client = QdrantClient(path=persist_dir)
        if not self.client.collection_exists(collection_name):
            self.client.create_collection(
                collection_name=collection_name,
                vectors_config=VectorParams(
                    size=self.embedding_function.dimension,
                    distance=Distance.COSINE,
                ),
            )

    def add_experience(self, experience: dict[str, Any]) -> str:
        """向记忆库中添加一条新的复盘经验"""
        from qdrant_client.models import PointStruct

        document = experience["document"]
        # 清洗并标准化元数据，确保 Qdrant可以正确存储
        metadata = _normalize_metadata(experience.get("metadata", {}))
        # 如果没有提供 ID，则基于元数据和文本内容生成一个确定性的 UUID
        experience_id = experience.get("id") or _build_experience_id(metadata, document)
        # payload用于 Qdrant中的精确过滤
        payload = {**metadata, "document": document}
        self.client.upsert(
            collection_name=self.collection_name,
            points=[
                PointStruct(
                    id=experience_id,
                    vector=self.embedding_function([document])[0],
                    payload=payload,
                )
            ],
        )
        return experience_id

    def search_creator_preferences(
        self,
        creator_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """根据创作者ID和查询词，检索最相关的历史经验"""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if self.client.count(collection_name=self.collection_name).count == 0:
            return []

        # 执行混合检索：向量相似度搜索 + 元数据精确过滤
        results = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embedding_function([query])[0], # 将用户的查询词转化为向量
            query_filter=Filter(
                must=[
                    FieldCondition(
                        key="creator_id",
                        match=MatchValue(value=creator_id),
                    )
                ]
            ),
            limit=limit,
            with_payload=True,
        )

        # 整理返回结果
        memories = []
        for point in results.points:
            payload = dict(point.payload or {})
            document = str(payload.pop("document", ""))
            memories.append(
                {
                    "id": str(point.id),
                    "document": document,
                    "metadata": payload,
                    "score": point.score,
                }
            )
        return memories

    def close(self) -> None:
        self.client.close()


def build_experience_document(state: dict[str, Any]) -> dict[str, Any]:
    """
    数据提取函数：将一次完整的分析状态（State）浓缩提炼成一段纯文本和结构化元数据，
    用于后续存入向量数据库。
    """
    raw_data = state.get("raw_data", {})
    metrics = state.get("metrics_summary", {})
    comments = state.get("comment_insights", {})
    content = state.get("content_insights", {})
    recommendations = state.get("recommendations", [])
    top_liked_comments = raw_data.get("top_liked_comments", [])

    topics = content.get("audience_interest_topics", [])
    signals = [label for label, _count in content.get("presentation_signals", [])]
    hot_keywords = [keyword for keyword, _count in comments.get("hot_keywords", [])]
    liked_comment_texts = [item.get("text", "") for item in top_liked_comments[:5]]

    # 拼装成一段总结文本，作为向量化的主体
    document = "\n".join(
        [
            f"标题：{raw_data.get('title', '')}",
            f"核心判断：{content.get('core_takeaway', '')}",
            f"观众兴趣选题：{', '.join(topics)}",
            f"呈现方式信号：{', '.join(signals)}",
            f"评论高频关键词：{', '.join(hot_keywords[:10])}",
            f"点赞前五评论：{' | '.join(liked_comment_texts)}",
            f"创作建议：{' | '.join(recommendations)}",
        ]
    )
    # 提取关键数据作为元数据，用于后续检索时的精确过滤和排序
    metadata = {
        "creator_id": state.get("creator_id", "default_creator"),
        "video_id": raw_data.get("video_id", state.get("video_id", "")),
        "platform": raw_data.get("platform", state.get("platform", "json")),
        "title": raw_data.get("title", ""),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "views": int(metrics.get("views", 0)),
        "likes": int(metrics.get("likes", 0)),
        "shares": int(metrics.get("shares", 0)),
        "like_rate": float(metrics.get("like_rate", 0)),
        "share_rate": float(metrics.get("share_rate", 0)),
    }
    return {"document": document, "metadata": metadata}


def build_memory_query(state: dict[str, Any]) -> str:
    """基于当前正在分析的视频特征，构建一条用于检索历史记忆的查询语句。"""
    raw_data = state.get("raw_data", {})
    content = state.get("content_insights", {})
    topics = ", ".join(content.get("audience_interest_topics", []))
    signals = ", ".join(label for label, _count in content.get("presentation_signals", []))
    title = raw_data.get("title") or state.get("video_id", "")
    return f"创作者历史偏好，标题：{title}，选题：{topics}，呈现方式：{signals}"


def format_memories_for_report(memories: list[dict[str, Any]]) -> list[str]:
    """将从向量数据库中取出的原始格式数据，格式化成 Markdown 报告中友好的展示文案。"""
    formatted = []
    for memory in memories:
        metadata = memory.get("metadata", {})
        title = metadata.get("title", "历史视频")
        views = metadata.get("views", 0)
        document = str(memory.get("document", "")).splitlines()
        takeaway = next((line.replace("核心判断：", "") for line in document if line.startswith("核心判断：")), "")
        formatted.append(f"{title}（阅读 {views:,}）：{takeaway or '暂无核心判断'}")
    return formatted


def _tokenize(text: str) -> list[str]:
    """
    内部辅助函数：简易的分词器。
    提取 2 个字以上的中文词组，或 2 个字符以上的英文/数字组合。
    同时使用 n-gram 思想切分长中文字符串，提高哈希命中率。
    """
    rough_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+-]{2,}", text.lower())
    tokens: list[str] = []
    for token in rough_tokens:
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    """
    内部辅助函数：清理元数据字典。
    Qdrant 等向量数据库的 Payload 只支持基本数据类型，这里过滤掉复杂的嵌套对象（强转为字符串）。
    """
    normalized: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if isinstance(value, (str, int, float, bool)):
            normalized[key] = value
        elif value is None:
            normalized[key] = ""
        else:
            normalized[key] = str(value)
    return normalized


def _build_experience_id(metadata: dict[str, Any], document: str) -> str:
    """
    内部辅助函数：基于核心内容生成确定性的 UUID。
    这样如果重复存入完全相同的视频复盘，ID 也会相同，Qdrant 会执行覆盖（更新）而不是重复添加。
    """
    seed = f"{metadata.get('creator_id', '')}:{metadata.get('video_id', '')}:{metadata.get('created_at', '')}:{document}"
    return str(uuid.UUID(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]))
