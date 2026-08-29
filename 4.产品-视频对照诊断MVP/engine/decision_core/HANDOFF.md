# 成员二 → 队员三交接说明（v0.2）

## 交付结论

本包是可注入现有 Agent 的餐饮决策内核，不是另一套聊天服务。它负责：

1. `DecisionRuntime`：连续执行已注册工具，在下一个用户/模型边界停止并保留轨迹。
2. `RestaurantSkillProvider`：根据会话事实和工具结果返回唯一下一动作。
3. 经营计算：确定性生成保本线、利润和现金跑道证据。
4. 现场视觉协议：把画面观察与经营推断分开，并绑定时间点。
5. 平台/私人 RAG：返回稳定证据 ID，私人数据强制按用户隔离。
6. 结论校验：禁止未知证据、纯推断强结论和超出当前许可的结论。

借鉴导师公开内容的方法，不自称导师，不打包其声音、形象、逐字稿或未经授权资料。

## 已确认的队员三目标环境

根据 2026-07-20《队员3进度及对接》：

- 白话建档和会后报告使用 `qwen3.7-plus`。
- 视频理解使用 `qwen3.5-omni-plus`。
- 实时连麦使用 `qwen3.5-omni-flash-realtime`，并组合 ASR、语义 VAD 和外部记忆。
- 后端已有私人 RAG、平台 RAG、经营计算、高德竞品和门店档案五类工具。
- 数据层已有用户、门店、视频、知识条目、诊断会话、事件、工具调用和复盘报告模型。
- 模型抽取的档案草稿必须经用户确认后才正式入库。

PDF 声称已提供任务二依赖注入接口，但文件本身没有仓库地址、类名、函数签名或 Schema 附件；完整时序图也渲染失败。因此当前包按上述五类工具对齐语义，但最终类名适配仍必须以队员三代码为准。

## 入口

- Agent 指令：`skill/restaurant-decision/SKILL.md`
- Python 包：`src/restaurant_handoff/`
- 平台知识：`knowledge/platform.jsonl`
- 知识版本：`knowledge/manifest.json`
- 向量索引构建：`scripts/build_index.py`
- 端到端接线示例：`examples/integration_example.py`
- 在线问题规划示例：`examples/live_question_planner.py`
- 确定性场景评测：`scripts/run_evals.py`
- 模型/人工评测：`evals/human-evaluation.md`

运行时只依赖 Python 标准库；生成百炼向量索引时需要网络和 `DASHSCOPE_API_KEY`。

## 验证

```bash
python3 -m unittest discover -s tests -v
python3 scripts/run_evals.py
python3 examples/integration_example.py
```

示例使用本地词法降级检索、确定性视觉夹具和高德夹具，只验证接线与证据轨迹，不代表真实在线模型或地图结果。生产接入必须替换标有 `demo`、`fixture`、`not-live` 的实现。

## 会话状态机

每次用户事实或工具结果变化后重新构造快照：

```python
directive = provider.next_directive(
    SessionSnapshot(
        stage=Stage.OPERATING_LOSS,
        facts=current_facts,
        evidence=current_evidence,
        hypotheses=current_hypotheses,
        available_tools=available_tools,
        tool_results=tool_results,
        user_id=authenticated_user_id,
        store_id=current_store_id,
        has_private_knowledge=has_private_knowledge,
    )
)
```

`directive.action` 有五种：

- `ask`：向用户追问一个事实。
- `plan_question`：后端没有注入语义问题规划器；实时模型必须从 `question_candidates` 中选一个，不能按列表顺序取第一项。
- `request_capture`：请求目标时段的六镜头现场视频。
- `call_tool`：调用 `tool_name`，原样传递 `tool_arguments`。
- `ready_for_judgment`：只允许从 `allowed_conclusions` 中选结论，并调用 `validate_judgment()`。

安全事实仍优先，但拍摄和工具调用已与追问交错：位置、品类和目标时段齐全即可拍摄；某工具参数齐全即可先调用，不需要等待完整问卷。

## 自动工具编排

将后端工具注册为返回 `ToolResult` 的函数：

```python
registry = ToolRegistry(
    {
        ToolName.BUSINESS_CALCULATION: calculate_business_metrics,
        ToolName.VISUAL_ANALYSIS: visual_adapter,
        ToolName.PLATFORM_RAG: platform_rag_adapter,
        ToolName.AMAP_COMPETITORS: amap_adapter,
    }
)
runtime = DecisionRuntime(provider, registry)
result = runtime.advance(snapshot)
```

运行时自动执行连续的 `call_tool`，在 `ask`、`plan_question`、`request_capture` 或 `ready_for_judgment` 时返回。`result.trace` 保存每一步 directive 和工具结果，可直接写入队员三的事件存储。未注册的关键工具不会被伪造，会触发 `insufficient_evidence`。

若队员三的 FastAPI/Realtime 工具为协程，使用同签名的 `AsyncToolRegistry` 和 `await AsyncDecisionRuntime(...).advance(snapshot)`，避免在实时事件循环中执行阻塞网络调用。

当快照同时有 `user_id` 和 `store_id` 时，Skill 会优先调用 `store_profile`。若返回 `data.facts`，运行时把缺失字段标成已核验工具事实，但绝不覆盖当前会话已有值。队员三必须保证该接口只返回用户已经确认入库的档案，不返回模型草稿。

## 问题规划器

后端可注入任意语言模型：

```python
planner = CallableModelQuestionPlanner(model_call)
provider = RestaurantSkillProvider(question_planner=planner)
```

如果实时后端没有现成模型客户端，可直接使用 OpenAI 兼容接口：

```bash
export RESTAURANT_MODEL_API_KEY='由安全环境提供'
export RESTAURANT_MODEL_BASE_URL='https://兼容接口/v1'
export RESTAURANT_MODEL_NAME='实际模型名'
python3 examples/live_question_planner.py
```

```python
client = OpenAICompatibleJsonClient.from_env()
planner = CallableModelQuestionPlanner(client)
```

API Key 只从环境读取，不进入配置文件、轨迹或错误消息。不同供应商若不支持 `response_format=json_object`，构造客户端时设置 `use_json_mode=False`，但返回内容仍必须是单个 JSON 对象。

`model_call(prompt)` 必须返回：

```json
{
  "fact_key": "候选列表中的一个键",
  "question": "一个简短中文问题",
  "rationale": "答案如何改变下一动作或结论"
}
```

模型选择候选范围外字段、问题为空或理由为空时直接报错，不自动伪造降级答案。

## 工具接入

后端工具统一映射为：

```json
{
  "status": "ok | no_hit | unavailable | forbidden | invalid_input | invalid_result",
  "evidence_ids": ["稳定证据 ID"],
  "data": {},
  "source": "工具与数据版本",
  "error_code": null
}
```

可用 `CallableEvidenceTool` 包装现有同步 API。`ok` 必须有来源和证据 ID；空返回、非对象返回和伪成功会被归为 `invalid_result`。

### 经营计算

直接调用 `calculate_business_metrics(arguments)`。语言模型不得自行替代保本计算。

### 视觉分析

用 `CallableVisionAnalyzer(model_call, model_name=...)` 包装现有多模态模型。模型返回的每项观察必须有画面时间点；每项推断必须有支持画面。视频引用应使用有权限的临时 URL 或开发对象 ID，不要写入平台知识库。

### 平台 RAG

正式环境推荐生成向量索引：

```bash
export DASHSCOPE_API_KEY='由安全环境提供，不写入项目'
python3 scripts/build_index.py
```

运行时使用 `ScopedVectorRetriever`，再通过 `retrieval_hits_to_result()` 变成统一工具结果。模型、维度和知识摘要必须与索引一致，否则拒绝加载。`LexicalFallbackRetriever` 只用于显式降级。

### 私人 RAG

私人条目沿用平台 Schema，但必须设置：

- `scope = "private"`
- `owner_id = 当前用户 ID`
- 每次搜索传入已认证 `user_id`

缺少用户 ID 抛出权限错误；不同用户的数据不能互相召回。

### 高德与当前工商信息

本包只提供窄适配接口，没有硬编码第三方凭证。队员三需要把现有高德和当前工商/备案查询实现映射为统一工具结果。POI 只作为当前地图事实，不能代替客流；历史 RAG 不能代替当前工商信息。

## 最终判断

模型生成 `Judgment` 后必须执行：

```python
errors = validate_judgment(
    judgment,
    snapshot,
    allowed_conclusions=directive.allowed_conclusions,
)
```

`errors` 非空时不得发送结论，应回到补证或降低为 `insufficient_evidence`。最终输出保留结论、决定性证据、反证/缺口、24 小时第一动作、验证条件和停止条件。

## 知识库状态

当前共 27 条：

- 6 张 `reviewed` 方法卡。
- 5 个 `golden` 案例，已对本地带时间点逐字稿做独立核对。
- 16 个 `secondary` 案例，只作为发现线索，不进入决定性检索。

五个黄金案例均缺少后续经营结果，因此只能支持当时的事实和推理链，不能声称建议已经被经营结果验证。正式扩充优先补有后续结果的反例与对照案例，而不是只增加视频数量。

## 仍需队员三提供的真实依赖

完成生产接入只缺具体实现，不缺协议：

1. 实际实时模型的名称、兼容地址和安全密钥注入方式。
2. 多模态视频 `model_call` 和媒体引用方式。
3. 高德适配器。
4. 当前工商/品牌信息适配器。
5. 私人知识库的认证用户 ID 与存储接口。
6. 队员三仓库中的依赖注入位置或抽象类签名。

拿到这些接口后只补适配层，不修改事实语义、证据等级、私人数据隔离和结论门槛。


