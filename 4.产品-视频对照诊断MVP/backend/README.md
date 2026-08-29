# 口袋餐谋：后端产品基座

这是“餐饮专家在线”升级后的口袋餐谋后端基座。它保留已经跑通的用户/门店建档、视频解析、实时连麦、经营工具、会话留痕和证据化复盘，并新增平台专家知识存储、`platform_rag` 和决策内核逐轮接入点。

## 已实现链路

```text
白话建档 → 提交用户刷到的成功案例 → Qwen Omni 案例解构
→ 实时视频连麦看用户现场 → 平台 RAG + 私人 RAG + 经营/地图工具
→ 决策内核逐轮追问与迁移判断 → 三段式证据化复盘
```

当前没有正式向量 RAG、决策内核、OSS 或高德 Key 时，系统仍可显式降级运行：

- 平台知识存放在独立的 `platform_knowledge_items` 表，不绑定用户或门店；私人知识继续按 `user_id + store_id` 隔离。
- `platform_rag` 默认使用数据库词法检索，正式环境通过 `PlatformKnowledgeRetrieverPort` 注入决策内核的 `ScopedVectorRetriever`。
- `SkillEnginePort` 同时支持建连指令和逐轮 `advance`；`DecisionCoreSkillEngineAdapter` 可包装其他贡献者的 `AsyncDecisionRuntime`。
- 文件使用本地安全存储；小于约 7.5 MB 的视频直接 Base64 送入 Omni，较大视频会使用同一百炼 Key 自动上传至 48 小时临时空间后解析。
- 正式生产环境仍通过 `ObjectStoragePort` 切换到长期 OSS 签名 URL，避免临时空间的限流与过期约束。
- 地图返回明确的不可用状态，不会伪造竞品；提供高德 Key 后自动启用适配器。

## 本地启动

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

在 `.env` 中填写百炼配置。不要把 `.env` 或 Key 提交到 Git。

```dotenv
YONGGE_DASHSCOPE_API_KEY=你的百炼业务空间Key
YONGGE_DASHSCOPE_HOST=你的业务空间Host
```

启动：

```powershell
.\.venv\Scripts\python.exe -m uvicorn yongge_online.main:app --reload
```

- Swagger：`http://127.0.0.1:8000/docs`
- OpenAPI：`http://127.0.0.1:8000/openapi.json`
- 健康检查：`http://127.0.0.1:8000/health`

## 平台知识导入

安装后可直接把主仓决策内核的知识文件导入后端：

```powershell
pocketmentor-import-platform-kb `
  ..\engine\decision_core\knowledge\platform.jsonl `
  --database-url "sqlite+aiosqlite:///./data/yongge_online.db"
```

导入使用版本化证据 ID：`rag:platform:<knowledge_id>:<version>`。重复导入会按该 ID 更新，不会因为重建向量索引改变报告证据。只有 `evidence_grade=reviewed|golden` 的条目进入默认决定性检索。

## 用户使用流程

1. `POST /api/v1/users` 创建用户。
2. `POST /api/v1/users/{user_id}/stores` 建立门店档案并录入经营数据。
3. `POST /api/v1/stores/{store_id}/videos` 上传用户刷到、希望迁移的成功案例。
4. `POST /api/v1/videos/{video_id}/analyze` 解析案例视频。
5. `POST /api/v1/stores/{store_id}/sessions` 创建诊断会话。
6. 获取 `GET /api/v1/realtime/config/{session_id}`，前端按配置建立 WebRTC。
7. 每个用户事实或工具结果边界可调用 `POST /api/v1/sessions/{session_id}/skill/advance` 获取决策内核的唯一下一动作。
8. Realtime 工具请求通过 `POST /api/v1/sessions/{session_id}/tools/execute` 执行并回传模型；其中 `platform_rag` 返回稳定知识证据 ID。
9. `POST /api/v1/sessions/{session_id}/complete` 生成报告。
10. `GET /api/v1/sessions/{session_id}/report` 获取复盘与行动方案。

视频上传同步保存，解析端点当前同步等待模型完成。移动端应显示 `uploaded / processing / completed / failed` 状态；后续可把同一 `VideoService.analyze` 放进任务队列，不改变 API 数据结构。

## 一键演示业务链

先启动 API，再使用一个小于 7.5 MB 的 MP4/MOV 视频：

```powershell
.\.venv\Scripts\python.exe scripts\demo_flow.py --video C:\path\to\sample.mp4
```

## 测试

不调用付费 API 的完整测试：

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m compileall -q src scripts
```

真实百炼冒烟测试只在显式设置 `RUN_LIVE_TESTS=1` 时运行：

```powershell
$env:RUN_LIVE_TESTS='1'
.\.venv\Scripts\python.exe -m pytest tests\live\test_qwen_live.py -q -s
```

该命令覆盖文本报告、公共 URL 视频、百炼临时文件上传往返、Realtime 连接，以及从 HTTP 上传到非降级报告的完整业务链。

## 接入与验证

- 接口接入：[`docs/integration-handoff.md`](docs/integration-handoff.md)


