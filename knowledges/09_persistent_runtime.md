# 当前运行态

SQLite 任务库、SQLite checkpointer 和 Redis SSE 缓存已从运行链路移除。

- Flask 任务状态和 SSE 事件只保存在内存中。
- LangGraph 不配置持久 checkpointer；当前流程不依赖审批中断恢复。
- 用户确认的经验和假设保存在 `local_data/experiences.json`。
- 服务重启会丢失未完成任务，但不会删除经验 JSON 文件。

此设计满足当前本地开发和单进程 Dashboard 需求，不包含多进程共享状态或任务恢复能力。
