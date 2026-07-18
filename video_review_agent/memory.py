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
    """Small deterministic embedding function for local Chroma storage.

    This keeps tests and local development independent from paid embedding APIs.
    It is not a replacement for a production embedding model, but it gives the
    agent a stable vector representation for creator-memory retrieval.
    """

    def __init__(self, dimension: int = 256) -> None:
        self.dimension = dimension

    def name(self) -> str:
        return "video-review-hash-embedding"

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in input]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        for token in _tokenize(text):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [round(value / norm, 6) for value in vector]


class CreatorMemoryStore:
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
        from qdrant_client.models import PointStruct

        document = experience["document"]
        metadata = _normalize_metadata(experience.get("metadata", {}))
        experience_id = experience.get("id") or _build_experience_id(metadata, document)
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
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        if self.client.count(collection_name=self.collection_name).count == 0:
            return []

        results = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embedding_function([query])[0],
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
    raw_data = state.get("raw_data", {})
    content = state.get("content_insights", {})
    topics = ", ".join(content.get("audience_interest_topics", []))
    signals = ", ".join(label for label, _count in content.get("presentation_signals", []))
    title = raw_data.get("title") or state.get("video_id", "")
    return f"创作者历史偏好，标题：{title}，选题：{topics}，呈现方式：{signals}"


def format_memories_for_report(memories: list[dict[str, Any]]) -> list[str]:
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
    rough_tokens = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_+-]{2,}", text.lower())
    tokens: list[str] = []
    for token in rough_tokens:
        tokens.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            tokens.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tokens


def _normalize_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
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
    seed = f"{metadata.get('creator_id', '')}:{metadata.get('video_id', '')}:{metadata.get('created_at', '')}:{document}"
    return str(uuid.UUID(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]))
