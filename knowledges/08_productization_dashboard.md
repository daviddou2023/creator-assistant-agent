# Dashboard 与 API

## 页面工作流

Dashboard 提供视频链接/BV 号、自然语言问题、创作者 ID、分析窗口和评论样本上限。用户可选择该创作者的历史假设供本次视频验证。

执行区显示动态 Todo、节点事件、按需取得的指标、评论信号、解释、证据、置信度、数据限制和可验证假设。页面不展示伪造的留存曲线。

报告完成后用户可确认并沉淀经验，或填写纠偏内容触发新任务。

## API

- `GET /api/health`: 服务状态。
- `GET /api/hypotheses?creator_id=...`: 读取可供后续验证的假设。
- `POST /api/reviews`: 创建复盘任务。
- `GET /api/reviews/<job_id>`: 读取当前进程中的任务结果。
- `GET /api/reviews/<job_id>/events`: 订阅进程内 SSE。
- `POST /api/reviews/<job_id>/feedback`: 确认报告或提交纠偏。

任务状态不会跨服务重启持久化。
