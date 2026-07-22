# 项目知识库入口

每次进入本项目，请先阅读本文件，再按任务需要阅读同目录下的专题文档。

## 阅读顺序

1. `01_project_overview.md`：理解项目目标、用户和能力边界。
2. `02_architecture.md`：理解 LangGraph 节点、状态流转和目录结构。
3. `03_langgraph_workflow.md`：查看当前 LangGraph 可视化流程和状态流转。
4. `04_vector_memory.md`：理解创作者历史偏好向量记忆的写入和检索。
5. `05_data_contract.md`：理解采集数据格式和后续平台接入约定。
6. `06_runbook.md`：理解如何启动、调试和扩展项目。
7. `07_checkpoint_resume.md`：理解 Plan 审批中断、检查点和恢复执行。

## 当前阶段

项目当前是一个可本地运行的 MVP：使用 JSON 样例数据模拟短视频平台数据采集，经过 LangGraph 节点生成视频流量复盘报告。后续可以把 `video_review_agent/collectors.py` 替换或扩展为真实平台 API、爬虫或数据库读取。

启动指令：
python test/test_bilibili_collector.py --bvid BV1xx411c7mD --top-liked-comments 5
生成完整报告
python demo.py --platform bilibili --video-id BV1xx411c7mD --top-liked-comments 5
