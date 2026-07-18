# 创作者向量记忆

项目引入本地 Qdrant 作为创作者经验记忆库。每次复盘结束后，agent 会把本次报告里的核心经验提取为一段文本，并向量化写入 Qdrant。下一次同一创作者执行复盘时，主图会先检索历史偏好，把结果放入 `historical_preferences` 状态字段，并在报告里输出“历史偏好参考”。

## 存储内容

每条经验由 `video_review_agent/memory.py` 生成，主要包含：

- 视频标题和核心判断。
- 观众兴趣选题。
- 有反馈的呈现方式。
- 评论高频关键词。
- 点赞前五评论。
- 本次创作建议。
- 指标元数据，如阅读量、点赞量、转发量、互动率。

## 向量化方式

当前使用 `HashEmbeddingFunction` 做本地确定性向量化，不依赖外部 embedding API，适合测试和本地开发。生产环境可以替换为更强的 embedding 模型，例如 DashScope、OpenAI embeddings 或自部署模型。

## 默认路径

默认 Qdrant 持久化目录：

```text
memory/qdrant
```

该目录已加入 `.gitignore`，不要提交到仓库。

## 命令行参数

```bash
python demo.py --creator-id creator_001 --memory-dir memory/qdrant
```

关闭记忆：

```bash
python demo.py --disable-memory
```
