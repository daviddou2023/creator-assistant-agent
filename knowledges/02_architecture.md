# 工程结构与组件职责

## 主流程

```text
自然语言问题
  -> Plan（必要 Todo + 可用指标 + 已确认经验）
  -> Execute（指标按键取数 / 评论抓取清洗 / 历史经验检索）
  -> Verify（证据、限制、置信度、候选解释、可验证假设）
  -> Re-plan（失败时最多两轮）
  -> Report
  -> 用户确认沉淀，或提交纠偏后定向重跑
```

## 目录

- `video_review_agent/workflow.py`: LangGraph 节点和有界重规划。
- `video_review_agent/reasoning.py`: LLM 计划生成与证据解释；不负责润色成稿。
- `video_review_agent/tools.py`: 指标选择、派生互动率和评论清洗。
- `video_review_agent/collectors.py`、`bilibili_collector.py`: JSON 与 B 站公开数据。
- `video_review_agent/experience_store.py`: 用户确认经验和假设的本地 JSON 存取。
- `video_review_agent/service_runtime.py`: Flask API、进程内任务和 SSE。
- `templates/dashboard.html`、`static/`: 复盘工作台。
- `demo.py`: CLI 入口。

## 运行态

任务状态、订阅者和 SSE 事件只在进程内存中。进程重启后任务不可恢复。经验文件默认位于 `local_data/experiences.json`，不使用 SQLite、Redis 或向量数据库。
