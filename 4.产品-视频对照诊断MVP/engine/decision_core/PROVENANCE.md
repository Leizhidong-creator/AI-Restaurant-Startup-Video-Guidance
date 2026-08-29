# decision_core 出处说明

原为我们自己的交付 `2.阶段二/.../交付包-v0.2/`,PocketMentor pivot 清理时该旧目录已删除、内容(含 tests/examples/evals/pyproject)合并到此处——**这里现在是决策内核的唯一家目录**。这是产品的"大脑"(护城河),自包含,运行时仅依赖 Python 标准库。

| 内容 | 作用 |
|---|---|
| `restaurant_handoff/`(11 模块) | 决策状态机 `RestaurantSkillProvider`/`DecisionRuntime`、平台+私人 RAG `ScopedVectorRetriever`、盈亏计算、视觉协议、结论校验 `validate_judgment`。 |
| `knowledge/platform.jsonl` | 经过来源标注与审校的平台知识库，当前 93 条；后端 importer 从这里导入。 |
| `knowledge/manifest.json` | 知识版本。 |
| `skill/restaurant-decision/` | Agent 指令与参考协议(问题树、证据契约、诊断维度)。 |
| `scripts/build_index.py` | 生成百炼向量索引(需 `DASHSCOPE_API_KEY`)。 |
| `scripts/run_evals.py` | 确定性场景评测。 |
| `HANDOFF.md` | 完整接口说明(接线新产品前必读)。 |

**校验**:`PYTHONPATH=engine/decision_core python3 -c "import restaurant_handoff"` 通过(纯标准库)。

**当前产品接入方式**：

1. 后端通过 `knowledge/importer.py` 将本目录的平台知识导入产品数据库，线上线下保持同源。
2. 后端通过 `integrations/decision_core.py` 适配检索与逐轮决策能力；实时链路按需调用轻量工具，重推理放在通话前后。


