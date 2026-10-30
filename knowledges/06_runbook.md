# 运行手册

## 安装依赖

```powershell
.\creator_env\Scripts\python.exe -m pip install -r requirements.txt
```

## 启动服务

```powershell
.\creator_env\Scripts\python.exe server.py
```

打开 `http://127.0.0.1:5000/`。任务和 SSE 事件保存在服务进程内存中；重启会清空运行任务。用户确认的经验保存在 `local_data/experiences.json`。

## CLI

```powershell
.\creator_env\Scripts\python.exe demo.py --platform bilibili --video-id BV1xx411c7mD --question "为什么点赞高但互动偏少？"
```

本地样例：

```powershell
.\creator_env\Scripts\python.exe demo.py --platform json --video-id demo-video-001 --question "观众对哪些呈现方式有反馈？"
```

## LLM 配置

在本地 `.env` 设置 `DEEPSEEK_API_KEY`、`VIDEO_REVIEW_LLM_PROVIDER` 和 `VIDEO_REVIEW_LLM_MODEL`。LLM 用于计划和证据解释，不用于报告润色。未配置时采用保守的观测摘要，不输出确定归因。

经验文件路径可通过 `VIDEO_REVIEW_EXPERIENCE_PATH` 覆盖。
