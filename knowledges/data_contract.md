# 数据契约

当前 MVP 支持两类数据源：

- `json`：使用 `data/sample_video_metrics.json` 作为平台数据模拟源。
- `bilibili`：使用 `bilibili-api-python` 调用哔哩哔哩公开接口，采集视频信息、当前统计数据和公开视频评论。

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
      ],
      "top_liked_comments": [
        {
          "created_at": "2026-07-11T10:10:00+08:00",
          "text": "点赞数较高的评论",
          "like": 100,
          "rpid": 123456,
          "user": "用户昵称"
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

## 哔哩哔哩数据源

命令行运行时使用：

```bash
python demo.py --platform bilibili --video-id BV1xx411c7mD --days 30 --max-comments 20
```

`video_id` 支持 BV 号、`av` 号或纯数字 aid。采集器会把 B 站返回的数据转换成与 mock 数据兼容的 `raw_data`：

- `metric_snapshots[0].views` 来自 B 站 `stat.view`。
- `metric_snapshots[0].likes` 来自 B 站 `stat.like`。
- `metric_snapshots[0].shares` 来自 B 站 `stat.share`。
- `comments[].text` 来自公开评论的 `content.message`。
- `comments[].created_at` 使用评论发布时间戳转换为 ISO 时间。
- `top_liked_comments` 优先使用 B 站公开评论明细接口采集，默认记录点赞数前五的公开评论；若公开接口返回不足，再使用 `bilibili-api-python` 兜底补充。

注意：B 站公开接口可能受风控、频率限制、地区网络、视频评论区设置等影响。测试脚本只做小样本冒烟测试，不用于高频抓取。

## 数据安全

- 不在样例数据中放真实用户隐私。
- 不在源码、文档、提交记录中保存平台 Cookie、Token 或 API Key。
- 如需调试真实数据，建议放在本地未提交的 `local_data/` 目录中。
