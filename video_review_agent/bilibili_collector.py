"""Bilibili collector built on public APIs via bilibili-api-python."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any


def collect_bilibili_video_data(
    video_id: str,
    days_after_publish: int,
    max_comments: int = 50,
    top_liked_comments_limit: int = 5,
) -> dict[str, Any]:
    """Sync wrapper for fetching one Bilibili video's metrics and comments."""

    return asyncio.run(
        collect_bilibili_video_data_async(
            video_id=video_id,
            days_after_publish=days_after_publish,
            max_comments=max_comments,
            top_liked_comments_limit=top_liked_comments_limit,
        )
    )


async def collect_bilibili_video_data_async(
    video_id: str,
    days_after_publish: int,
    max_comments: int = 50,
    top_liked_comments_limit: int = 5,
) -> dict[str, Any]:
    """Fetch video metadata, latest metrics, and public comments from Bilibili."""
    
    # 尝试导入bilibili_api 库
    try:
        from bilibili_api import comment, video
    except ImportError as exc:
        raise RuntimeError(
            "bilibili-api-python is required for Bilibili collection. "
            "Install it with: pip install bilibili-api-python"
        ) from exc

    # 解析视频 ID 并构建 Video对象
    bili_video = _build_video(video, video_id)
    # 获取视频的基本信息 （需要 await 等待网络请求）
    info = await bili_video.get_info()
    # 提取统计数据
    stat = info.get("stat", {})
    # 提取发布时间
    publish_time = datetime.fromtimestamp(int(info["pubdate"]), tz=timezone.utc)
    # 记录当前抓取数据的时间
    captured_at = datetime.now(timezone.utc)

    # 按照抓取时间排序的普通评论
    comments = await _collect_comments(
        comment_module=comment,
        aid=int(info["aid"]),
        publish_time=publish_time,
        cutoff=publish_time + timedelta(days=days_after_publish),
        max_comments=max_comments,
    )

    # 先直接通过 requests 请求 B站 公开接口获取高赞评论
    top_liked_comments = _collect_top_liked_comments_from_public_api(
        aid=int(info["aid"]),
        bvid=str(info.get("bvid", video_id)),
        limit=top_liked_comments_limit,
    )
    # 如果直接请求获取的高赞评论数量不够，则回退使用bilibili_api 库继续抓取
    if len(top_liked_comments) < top_liked_comments_limit:
        top_liked_comments = await _collect_top_liked_comments(
            comment_module=comment,
            aid=int(info["aid"]),
            limit=top_liked_comments_limit,
            existing_comments=top_liked_comments,
        )

    # 将抓取到的所有数据打包成标准化的字典返回
    return {
        "platform": "bilibili",
        "video_id": info.get("bvid", video_id),
        "aid": info.get("aid"),
        "title": info.get("title", ""),
        "description": info.get("desc", ""),
        "published_at": publish_time.isoformat(),
        "owner": info.get("owner", {}),
        "metric_snapshots": [
            {
                "captured_at": captured_at.isoformat(),
                "views": int(stat.get("view", 0)),
                "likes": int(stat.get("like", 0)),
                "shares": int(stat.get("share", 0)),
                "favorites": int(stat.get("favorite", 0)),
                "coins": int(stat.get("coin", 0)),
                "danmaku": int(stat.get("danmaku", 0)), # 弹幕数
                "reply": int(stat.get("reply", 0)), # 评论数
            }
        ],
        "comments": comments,
        "top_liked_comments": top_liked_comments,
        "raw_stat": stat, # 保留最原始的统计数据以备不时之需
    }


async def _collect_comments(
    comment_module: Any,
    aid: int,
    publish_time: datetime,
    cutoff: datetime,
    max_comments: int,
) -> list[dict[str, Any]]:
    """分页循环抓取视频评论，只保留在发布时间和截止时间内的评论"""
    comments: list[dict[str, Any]] = []
    offset = ""
    seen_offsets: set[str] = set()

    while len(comments) < max_comments:
        # 使用懒加载模式按时间顺序获取评论
        payload = await comment_module.get_comments_lazy(
            aid,
            comment_module.CommentResourceType.VIDEO,
            offset=offset,
            order=comment_module.OrderType.TIME,
        )
        replies = payload.get("replies") or []
        for reply in replies:
            # 解析每条评论的创建时间
            created_at = datetime.fromtimestamp(int(reply.get("ctime", 0)), tz=timezone.utc)
            # 时间cutoff过滤
            if publish_time <= created_at <= cutoff:
                comments.append(_normalize_reply(reply))
            if len(comments) >= max_comments:
                break

        cursor = payload.get("cursor") or {}
        next_offset = str(cursor.get("next", ""))
        if cursor.get("is_end") or not next_offset or next_offset in seen_offsets:
            break
        seen_offsets.add(next_offset)
        offset = next_offset

    return comments


async def _collect_top_liked_comments(
    comment_module: Any,
    aid: int,
    limit: int = 5,
    existing_comments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """使用bilibili_api库作为备用手段获取高赞评论"""
    comments: list[dict[str, Any]] = list(existing_comments or [])
    seen_rpids: set[int] = {int(item.get("rpid", 0)) for item in comments}

    first_page = await comment_module.get_comments(
        aid,
        comment_module.CommentResourceType.VIDEO,
        page_index=1,
        order=comment_module.OrderType.LIKE,
    )
    _append_unique_replies(comments, seen_rpids, first_page.get("replies") or [], limit)

    # 数量不够，启动懒加载继续往后翻页抓取按点赞排序的评论
    if len(comments) < limit:
        await _append_lazy_comments(
            comment_module=comment_module,
            aid=aid,
            order=comment_module.OrderType.LIKE,
            comments=comments,
            seen_rpids=seen_rpids,
            limit=limit,
        )

    # 如果还凑不齐数量，则退化为按照时间排序抓取第一页来凑数
    if len(comments) < limit:
        fallback_page = await comment_module.get_comments(
            aid,
            comment_module.CommentResourceType.VIDEO,
            page_index=1,
            order=comment_module.OrderType.TIME,
        )
        _append_unique_replies(comments, seen_rpids, fallback_page.get("replies") or [], limit)

    comments.sort(key=lambda item: item.get("like", 0), reverse=True)
    return comments[:limit]


def _collect_top_liked_comments_from_public_api(
    aid: int,
    bvid: str,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    直接通过 HHTP 请求 B站的公开接口 (v2/reply/main) 抓取高赞评论
    这是一个轻量级的同步函数，避开了 bilibili_api 庞杂的依赖，速度更快更适合直接抓取高赞评论
    
    
    """
    if limit <= 0:
        return []

    try:
        import requests
    except ImportError:
        return []

    try:
        response = requests.get(
            "https://api.bilibili.com/x/v2/reply/main",
            params={
                "jsonp": "jsonp",
                "next": 0,
                "type": 1,
                "oid": aid,
                "mode": 3,
                "plat": 1,
                "ps": min(max(limit, 5), 20),
            },
            headers={
                "User-Agent": "Mozilla/5.0", # 伪装成普通浏览器
                "Referer": f"https://www.bilibili.com/video/{bvid}", # B站的防盗链机制，必须带上bvid
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []

    if payload.get("code") != 0:
        return []

    replies = (payload.get("data") or {}).get("replies") or []
    comments = [_normalize_reply(reply) for reply in replies]
    comments.sort(key=lambda item: item.get("like", 0), reverse=True)
    return comments[:limit]


async def _append_lazy_comments(
    comment_module: Any,
    aid: int,
    order: Any,
    comments: list[dict[str, Any]],
    seen_rpids: set[int],
    limit: int,
) -> None:
    offset = ""
    seen_offsets: set[str] = set()

    while len(comments) < limit:
        payload = await comment_module.get_comments_lazy(
            aid,
            comment_module.CommentResourceType.VIDEO,
            offset=offset,
            order=order,
        )
        _append_unique_replies(comments, seen_rpids, payload.get("replies") or [], limit)

        cursor = payload.get("cursor") or {}
        next_offset = str(cursor.get("next", ""))
        if cursor.get("is_end") or not next_offset or next_offset in seen_offsets:
            break
        seen_offsets.add(next_offset)
        offset = next_offset


def _append_unique_replies(
    comments: list[dict[str, Any]],
    seen_rpids: set[int],
    replies: list[dict[str, Any]],
    limit: int,
) -> None:
    """内部辅助函数：遍历传入的原始评论数据，去重格式化后追加到 comments列表中"""
    for reply in replies:
        rpid = int(reply.get("rpid", 0))
        if rpid in seen_rpids:
            continue
        seen_rpids.add(rpid)
        comments.append(_normalize_reply(reply))
        if len(comments) >= limit:
            break


def _normalize_reply(reply: dict[str, Any]) -> dict[str, Any]:
    """
    数据清理：将B站原始庞大且嵌套深的评论字典，精简提取出我们需要的基础字段
    """
    created_at = datetime.fromtimestamp(int(reply.get("ctime", 0)), tz=timezone.utc)
    return {
        "created_at": created_at.isoformat(),
        "text": (reply.get("content") or {}).get("message", ""),
        "like": int(reply.get("like", 0)),
        "rpid": reply.get("rpid"),
        "user": (reply.get("member") or {}).get("uname", ""),
    }


def _build_video(video_module: Any, video_id: str) -> Any:
    """识别传入的ID类型，并构造 bilibili_api对应的 Video实例"""
    normalized = video_id.strip()
    if normalized.upper().startswith("BV"):
        return video_module.Video(bvid=normalized)
    if normalized.lower().startswith("av"):
        return video_module.Video(aid=int(normalized[2:]))
    if normalized.isdigit():
        return video_module.Video(aid=int(normalized))
    raise ValueError("Bilibili video id must be a BV id, av id, or numeric aid.")
