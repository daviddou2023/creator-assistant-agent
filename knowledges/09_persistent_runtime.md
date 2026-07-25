# 服务运行态持久化设计

本文档说明服务化之后，前端和后端交互产生的运行态数据如何持久化。

## 目标

原始版本中，Flask 服务的任务状态、SSE 事件历史和 LangGraph Checkpoint 主要存在 Python 进程内存中。服务重启后，前端无法继续查询历史任务，也无法跨进程恢复等待审批的图执行状态。

当前扩展后的目标是：

- SQLite 存任务快照。
- Redis 存 SSE 事件缓存。
- LangGraph 使用 SQLite checkpointer 存图执行检查点。

## 存储位置

默认配置位于 `.env.example`：

```bash
VIDEO_REVIEW_JOB_DB=local_data/review_jobs.sqlite3
VIDEO_REVIEW_CHECKPOINT_BACKEND=sqlite
VIDEO_REVIEW_CHECKPOINT_DB=local_data/langgraph_checkpoints.sqlite3
VIDEO_REVIEW_EVENT_CACHE=auto
VIDEO_REVIEW_REDIS_URL=redis://localhost:6379/0
VIDEO_REVIEW_EVENT_CACHE_TTL_SECONDS=86400
VIDEO_REVIEW_EVENT_CACHE_MAX_EVENTS=500
```

默认本地文件：

```text
local_data/review_jobs.sqlite3          # Flask 任务快照
local_data/langgraph_checkpoints.sqlite3 # LangGraph 检查点
memory/qdrant/                          # 创作者长期向量记忆
```

`local_data/` 已在 `.gitignore` 中，运行数据不会被提交到 GitHub。

## SQLite 任务存储

实现位置：

```text
video_review_agent/job_store.py
video_review_agent/service.py
```

SQLite 表：

```sql
review_jobs (
    job_id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    request_json TEXT NOT NULL,
    plan_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)
```

保存内容：

- 用户提交的视频链接、平台、创作者 ID 等请求参数。
- 当前任务状态：`queued`、`running`、`awaiting_approval`、`completed`、`rejected`、`failed`。
- Plan 审批内容。
- 最终报告、Dashboard 图表数据、分析结果。
- 错误堆栈。

服务重启后，只要 `job_id` 仍然存在，就可以通过：

```http
GET /api/reviews/<job_id>
```

重新读取任务状态和最终结果。

## Redis SSE 事件缓存

实现位置：

```text
video_review_agent/event_cache.py
video_review_agent/service.py
```

Redis Key 格式：

```text
video_review_agent:sse:<job_id>
```

缓存内容是 SSE 事件列表，包括：

- `run_started`
- `node_update`
- `dashboard_update`
- `interrupted`
- `resume_started`
- `run_resumed`
- `completed`
- `rejected`
- `error`

用途：

- 前端刷新页面后，可以重新订阅 `/api/reviews/<job_id>/events` 并回放最近事件。
- 事件缓存设置 TTL，避免 Redis 无限增长。
- 每个任务最多保留 `VIDEO_REVIEW_EVENT_CACHE_MAX_EVENTS` 条事件。

本地开发时，`VIDEO_REVIEW_EVENT_CACHE=auto` 会优先尝试 Redis。如果没有安装 `redis` 包或本机没有启动 Redis，会自动降级到内存缓存。生产环境建议设置：

```bash
VIDEO_REVIEW_EVENT_CACHE=redis
```

这样 Redis 不可用时服务会直接暴露错误，便于运维发现问题。

## LangGraph SQLite Checkpointer

实现位置：

```text
video_review_agent/checkpointing.py
video_review_agent/graph.py
```

依赖：

```text
langgraph-checkpoint-sqlite
```

用途：

- 当图执行到 `plan_review_node` 时触发 `interrupt(plan)`。
- Checkpointer 保存图状态和当前线程 ID。
- 前端展示 Plan，用户确认或修改后调用 `/api/reviews/<job_id>/resume`。
- 后端使用相同 `thread_id` 和 `Command(resume=...)` 继续执行。

本地验证：

```bash
python test/test_checkpoint_interrupt.py
python test/test_service_persistence.py
```

如果当前环境未安装 `langgraph-checkpoint-sqlite`，代码会临时回退到 `MemorySaver`，但跨进程恢复能力需要安装依赖后才完整具备：

```bash
pip install -r requirements.txt
```

## 服务启动

启动 Redis：

```bash
redis-server
```

启动 Flask：

```bash
python server.py
```

健康检查：

```http
GET /api/health
```

返回中会包含当前任务存储和事件缓存后端：

```json
{
  "status": "ok",
  "job_store": "local_data/review_jobs.sqlite3",
  "event_cache": "redis"
}
```

## 当前边界

- 活跃 SSE 连接仍然是进程内对象，因为 HTTP 长连接不能直接存入数据库。
- Redis 存的是事件历史缓存，不负责执行后台任务。
- SQLite 适合本地和面试项目演示；生产环境可以把任务存储升级到 PostgreSQL，把后台执行升级到 Celery/RQ。
