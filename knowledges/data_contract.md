# 数据契约

当前 MVP 使用 `data/sample_video_metrics.json` 作为平台数据模拟源。

## 输入字段

```json
{
  "videos": [
    {
      "video_id": "demo-video-001",
      "title": "视频标题",
      "description": "视频描述",
      "published_at": "2026-07-10T09:00:00+08:00",
      "metric_snapshots": [
        {
          "captured_at": "2026-07-11T09:00:00+08:00",
          "views": 4200,
          "likes": 302,
          "shares": 63
        }
      ],
      "comments": [
        {
          "created_at": "2026-07-11T10:10:00+08:00",
          "text": "评论内容"
        }
      ]
    }
  ]
}
```

## 真实平台接入建议

后续接入真实平台时，优先保持输出给 graph 的 `raw_data` 结构不变。不同平台的数据采集差异应封装在 `collectors.py` 或新的 collector 类里。

建议平台采集层提供这些能力：

- 根据视频 ID 查询视频基础信息。
- 根据发布时间和分析窗口查询指标快照。
- 拉取评论文本、评论时间、点赞量和回复关系。
- 记录采集时间，方便分析视频生命周期中的增长节奏。

## 数据安全

- 不在样例数据中放真实用户隐私。
- 不在源码、文档、提交记录中保存平台 Cookie、Token 或 API Key。
- 如需调试真实数据，建议放在本地未提交的 `local_data/` 目录中。
