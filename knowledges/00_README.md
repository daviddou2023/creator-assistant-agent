# 项目知识库入口

进入项目先读本文件，再按任务读取专题文档。

## 当前架构

面向短视频创作者的证据驱动复盘助手。用户提交带 BV 号的视频链接和自然语言问题，LangGraph 生成有限任务清单，按需获取公开指标、评论或已确认经验，整理证据后由模型提出解释与可验证假设。任务失败时最多重规划两轮。报告反馈可以触发重跑；用户确认后才写入本地经验库。

## 文档

- `01_project_overview.md`: 目标和边界。
- `02_architecture.md`: 组件和职责。
- `03_langgraph_workflow.md`: 计划、执行、核验和反馈路径。
- `04_experience_hypotheses.md`: 本地经验与假设存储。
- `05_data_contract.md`: 数据字段与平台限制。
- `06_runbook.md`: 安装、运行和配置。
- `07_checkpoint_resume.md`: 报告纠偏和后续验证。
- `08_productization_dashboard.md`: Dashboard 与 API。
- `09_persistent_runtime.md`: 当前进程状态和本地经验文件。

## 常用命令

```powershell
.\creator_env\Scripts\python.exe demo.py --platform bilibili --video-id BV1xx411c7mD --question "为什么点赞率高但评论互动偏少？"
.\creator_env\Scripts\python.exe server.py
```
