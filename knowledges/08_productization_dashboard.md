# 服务化与可视化 Dashboard

本项目新增轻量级 Flask 服务，把 LangGraph 复盘流程封装为 RESTful API，并通过 Server-Sent Events 推送每个节点的执行状态。前端 Dashboard 通过原生 HTML/CSS/JS 展示节点进度、Plan 审批、指标卡片、趋势图和最终报告。

## 文件位置

```text
server.py                         # Flask 启动入口
video_review_agent/service.py     # REST API、SSE、后台任务管理
video_review_agent/dashboard.py   # data_analyst 节点的图表数据构造
templates/dashboard.html          # Dashboard 页面
static/dashboard.js               # 前端交互、SSE、Canvas 图表
static/dashboard.css              # 页面样式
```

## 后端 API

启动服务：

```bash
python server.py
```

健康检查：

```http
GET /api/health
```

创建复盘任务：

```http
POST /api/reviews
Content-Type: application/json

{
  "video_url": "https://www.bilibili.com/video/BV1xx411c7mD",
  "creator_id": "creator_001",
  "platform": "auto",
  "days_after_publish": 7,
  "max_comments": 50,
  "top_liked_comments_limit": 5,
  "require_plan_approval": true,
  "memory_enabled": false
}
```

返回：

```json
{
  "job_id": "...",
  "thread_id": "...",
  "status": "queued",
  "events_url": "/api/reviews/<job_id>/events",
  "result_url": "/api/reviews/<job_id>",
  "resume_url": "/api/reviews/<job_id>/resume"
}
```

查询任务状态：

```http
GET /api/reviews/<job_id>
```

订阅 SSE：

```http
GET /api/reviews/<job_id>/events
```

恢复 Plan：

```http
POST /api/reviews/<job_id>/resume
Content-Type: application/json

{
  "resume_payload": {
    "approved": true,
    "recommendations": ["用户修改后的建议 1", "用户修改后的建议 2"],
    "review_notes": "Dashboard 用户确认后恢复执行"
  }
}
```

## SSE 事件类型

- `run_started`：后台任务开始。
- `node_update`：某个 LangGraph 节点完成。
- `dashboard_update`：`data_analyst` 节点输出图表数据。
- `interrupted`：`plan_review` 中断，等待用户确认。
- `resume_started` / `run_resumed`：用户确认后恢复执行。
- `completed`：报告生成完成。
- `rejected`：用户拒绝 Plan，流程结束。
- `error`：任务失败。
- `heartbeat`：长连接保活。

## Dashboard 图表数据

`data_analyst_node` 通过 `video_review_agent/dashboard.py` 输出 `dashboard_data`，前端直接消费，不重复计算：

- `cards`：阅读量、点赞量、转发量、评论量和互动率。
- `trend_points`：每个指标快照的 views、likes、shares、engagement_rate。
- `retention_curve`：按快照播放量归一化后的热度留存走势。
- `engagement_curve`：互动率走势。
- `sentiment`：正向、中性、负向评论数量。
- `top_keywords`：评论高频关键词。

注意：当前“留存”是基于发布后指标快照估算的热度留存指数，不等同于平台后台的逐秒观看留存。
