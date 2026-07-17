# 工程结构与 LangGraph 流程

## 目录结构

```text
.
├── demo.py                         # 命令行入口
├── langgraph.json                  # LangGraph 应用配置
├── pyproject.toml                  # 本地包与依赖元数据
├── requirements.txt                # Python 依赖
├── .env.example                    # 本地秘钥配置示例
├── data/                           # 本地样例数据
├── knowledges/                     # 项目说明文档
└── video_review_agent/             # agent 核心代码
    ├── graph.py                    # LangGraph 节点和边
    ├── state.py                    # 图状态定义
    ├── collectors.py               # 数据采集层
    ├── bilibili_collector.py       # 哔哩哔哩公开数据采集
    ├── analytics.py                # 规则分析层
    ├── reporting.py                # 报告渲染
    ├── llm.py                      # 可选 LLM 润色
    └── config.py                   # 环境变量配置
```

## LangGraph 节点

1. `collect_data`：读取指定视频在分析窗口内的指标快照和评论。
2. `summarize_metrics`：生成总阅读量、点赞量、转发量、评论量及互动率。
3. `analyze_comments`：分析评论情绪、关键词、高频问题和代表性评论。
4. `infer_content`：归纳观众更感兴趣的选题和呈现方式。
5. `recommend`：生成下一步创作建议。
6. `render_report`：输出 Markdown 报告，可选择用 LLM 润色。

## 设计原则

- 数据采集、指标计算、内容分析和报告生成分层，便于替换真实平台数据源。
- `collect_data` 当前支持 `json` mock 数据和 `bilibili` 真实数据源。
- 默认不依赖 LLM 也能输出稳定报告。
- LLM 只做报告润色或高级归纳，不负责不可验证的原始数据计算。
- 所有秘钥只从环境变量读取，不写入源码和文档。

## LangGraph 应用配置

根目录的 `langgraph.json` 暴露 `video_review_agent` 图，入口为 `./video_review_agent/graph.py:graph`。本地命令行调试继续使用 `demo.py`，部署或 Studio 调试时优先使用 `langgraph.json`。
