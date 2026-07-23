# 运行与扩展手册

## 启动

```bash
python demo.py
```

默认会把报告保存到 `reports/<video_id>_<timestamp>/report.md`，终端只输出报告文件路径。

如果本机没有全局 Python，也可以用 `uv` 临时环境运行：

```bash
uv run --with-requirements requirements.txt python demo.py
```

指定视频、分析窗口和报告根目录：

```bash
python demo.py --video-id demo-video-001 --days 7 --reports-dir reports
```

如需完全指定输出文件路径，也可以使用：

```bash
python demo.py --output reports/manual/report.md
```

使用哔哩哔哩真实数据源：

```bash
python demo.py --platform bilibili --video-id BV1xx411c7mD --days 30 --max-comments 20 --top-liked-comments 5
```

指定创作者 ID 并启用历史偏好记忆：

```bash
python demo.py --creator-id creator_001 --memory-dir memory/qdrant
```

如果临时不想读写向量记忆：

```bash
python demo.py --disable-memory
```

测试创作者记忆写入和检索：

```bash
python test/test_creator_memory.py
```

测试 Plan 审批中断和恢复：

```bash
python test/test_checkpoint_interrupt.py
```

启动 Flask 服务和 Dashboard：

```bash
python server.py
```

启动后访问：

```text
http://127.0.0.1:5000/
```

测试服务 API：

```bash
python test/test_service_api.py
```

生成待确认 Plan 文件：

```bash
python demo.py --require-plan-approval --thread-id demo-plan-review
```

单独测试 B 站采集器：

```bash
python test/test_bilibili_collector.py --bvid BV1xx411c7mD --days 30 --max-comments 10 --top-liked-comments 5
```

如需启用 LLM 润色，请先在本地 `.env` 配置对应 API Key，例如 `DEEPSEEK_API_KEY`，然后运行：

```bash
python demo.py --use-llm
```

`.env` 可参考根目录的 `.env.example`，真实秘钥不要提交到项目里。

## 扩展真实数据源

1. 在 `video_review_agent/collectors.py` 中新增平台采集函数或类。
2. 保持返回字段兼容 `05_data_contract.md`。
3. 在 `graph.py` 的 `collect_data_node` 中按配置选择数据源。
4. 给新数据源补充小样本数据，避免只靠线上接口调试。

## 常见开发任务

- 增加指标：修改 `analytics.py` 的 `summarize_metrics`，再在 `reporting.py` 输出。
- 增加评论分析维度：修改 `analytics.py` 的 `analyze_comments`。
- 调整创作建议：修改 `analytics.py` 的 `build_recommendations`。
- 调整报告格式：修改 `reporting.py`。

## 进入项目时的约定

每次开始开发前先读 `knowledges/00_README.md`，再根据任务阅读相关文档。新增重要能力时，同步更新 `knowledges` 目录中的说明。
