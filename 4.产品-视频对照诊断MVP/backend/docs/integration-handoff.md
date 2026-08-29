# 任务 3 与其他模块的交接契约

## 前端接入

前端不保存百炼永久 Key。实时连麦顺序：

1. 创建诊断会话。
2. 请求 `GET /api/v1/realtime/config/{session_id}`。
3. 浏览器采集音频和可选视频；视频发送建议降至 2 FPS。
4. 把 Offer SDP 原文 POST 到配置中的 `sdp_endpoint`，Content-Type 为 `application/sdp`。
5. 将 Answer SDP 设置为远端描述。
6. DataChannel 收到 `session.created` 后发送接口返回的 `session_update`，然后解除媒体门控。
7. 收到 `response.function_call_arguments.done` 时，把 `call_id`、`name` 和 JSON arguments POST 到 `/sessions/{session_id}/tools/execute`。
8. 将后端工具结果通过 `conversation.item.create` 的 `function_call_output` 事件回传 Realtime，再发送 `response.create`。
9. 把最终用户/AI 转写和关键观察写入 `/sessions/{session_id}/events`。
10. 结束媒体轨道后调用 `/sessions/{session_id}/complete`。

前端需要处理的状态：摄像头/麦克风权限拒绝、SDP 失败、连接中断、AI 思考、工具执行、视频解析进度和报告降级标识 `is_fallback`。

## 平台知识与 RAG 接入

后端现在明确分开两个 Port。

私人知识：

```python
async def search(
    *, user_id: str, store_id: str, query: str, limit: int
) -> list[KnowledgeHit]
```

平台知识：

```python
async def search(
    *, query: str, limit: int,
    category: str | None = None,
    stage: str | None = None,
    region: str | None = None,
) -> list[KnowledgeHit]
```

通过 `create_app(private_retriever_factory=..., platform_retriever_factory=...)` 注入，服务开发不会再写死数据库检索器。`DecisionCorePlatformRetrieverAdapter` 已把同步 `ScopedVectorRetriever` 包装成不阻塞事件循环的异步平台 Port。

平台知识位于 `platform_knowledge_items`，与私人知识物理分表。先运行：

```powershell
pocketmentor-import-platform-kb `
  ..\engine\decision_core\knowledge\platform.jsonl `
  --database-url "sqlite+aiosqlite:///./data/yongge_online.db"
```

返回条目必须保留稳定 `id`、知识版本、来源、内容、类型、标签、时间点、审核状态和相关度。主仓 `platform.jsonl` 的证据 ID 为 `rag:platform:<knowledge_id>:<version>`；重建向量索引不能修改它。

推荐正式检索链：结构化权限过滤 → text-embedding-v4 召回 → qwen3-rerank → `KnowledgeHit`。平台知识和私人知识应使用不同命名空间，私人检索强制携带 `user_id` 与 `store_id`。

### `platform_rag` 工具结果

```json
{
  "status": "ok | no_hit | unavailable",
  "evidence_ids": ["rag:platform:method-site-001:2.0"],
  "data": {"hits": []},
  "source": "platform_knowledge",
  "error_code": null
}
```

会后报告只接受本会话已完成 `platform_rag` 工具调用真正返回、且数据库中存在的知识 ID；未知或伪造 ID 仍会触发降级报告。

## Skill / 决策内核接入

实现 `src/yongge_online/skills/ports.py` 中的 `SkillEnginePort`：

```python
async def build_session_instructions(context: SkillContext) -> str
async def advance(context: SkillSessionContext) -> SkillAdvanceResult
```

`SkillSessionContext` 由后端提供已认证的用户/门店、会话事件、工具调用以及当前事实/证据。`advance` 返回 `ask / plan_question / request_capture / call_tool / ready_for_judgment` 中的唯一下一动作。

`POST /api/v1/sessions/{session_id}/skill/advance` 调用该 Port，并把返回结果保存为 `skill_directive` 会话事件。其他贡献者的决策内核通过 `DecisionCoreSkillEngineAdapter(runtime=AsyncDecisionRuntime(...), snapshot_builder=...)` 接入，不需要复制或改写其算法。

Skill 负责问题树、追问顺序、何时看现场、何时检索和何时计算；不得直接访问数据库或返回虚构工具结果。替换时通过 `create_app(..., skill_engine=...)` 注入。

## OSS 接入

实现 `ObjectStoragePort.save/read/model_url`。`model_url` 应返回短期签名 URL，并满足模型服务可公网下载、包含正确 `Content-Type` 和 `Content-Length`。业务表只保存 `storage_uri`，不保存永久公开 URL。

当前开发链路不依赖正式 OSS：小视频以内联 Base64 调用，大视频由 `DashScopeTemporaryFileUploader` 使用同一百炼 Key 暂存并立即解析。百炼临时 URL 仅用于开发/演示演示，48 小时过期且不可用于高并发；队员接入正式 OSS 后，`ObjectStoragePort.model_url` 返回值会优先于临时上传路径。

## 高德接入

当前已实现 `AmapWebServiceProvider`。在环境变量中增加：

```dotenv
YONGGE_AMAP_WEB_SERVICE_KEY=你的Web服务Key
```

必须使用“Web 服务 API Key”，不是前端 JS Key。前端不直接调用高德 Web 服务，避免暴露 Key。地图失败或门店缺少经纬度时，工具返回 `available=false`，Agent 必须追问或声明信息缺口。

## 报告契约

报告问题只能引用三类 ID：

- `knowledge_item`
- `tool_call`
- `session_event`

后端会校验引用是否真实存在。任何未知引用都会触发降级报告，从而防止模型把没有依据的判断包装成事实。


