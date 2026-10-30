# 证据驱动短视频复盘助手

面向短视频创作者的 LangGraph 应用。提交视频链接/BV 号和自然语言问题后，系统按需采集公开指标和评论，计算互动指标，生成带证据、置信度、限制和可验证假设的复盘。

## 运行

```powershell
.\creator_env\Scripts\python.exe -m pip install -r requirements.txt
.\creator_env\Scripts\python.exe server.py
```

打开 `http://127.0.0.1:5000/`。

CLI 示例：

```powershell
.\creator_env\Scripts\python.exe demo.py --platform bilibili --video-id BV1xx411c7mD --question "为什么点赞率高但评论互动偏少？"
```

本地样例可使用 `--platform json --video-id demo-video-001`。

## 架构摘要

`Plan -> Execute -> Verify -> Re-plan（失败时最多两轮）-> Report -> 用户反馈 -> 经验沉淀/纠偏重跑`。

用户确认的经验保存在 `local_data/experiences.json`，使用本地词项检索，不使用 Qdrant。任务和 SSE 事件在进程内存中，重启服务后丢失。服务不依赖 SQLite 或 Redis。

## 数据限制

B 站公开接口能获取部分累计互动指标和公开评论，通常没有历史快照，也不提供 5 秒跳出率、平均播放时长、完播率或真实观看留存曲线。报告会标记这些缺失；单条视频观察不能证明因果关系。

LLM 通过 `.env` 中的 `DEEPSEEK_API_KEY` 用于任务规划和证据解释，不做报告润色。配置说明见 [项目知识库](knowledges/00_README.md)。
