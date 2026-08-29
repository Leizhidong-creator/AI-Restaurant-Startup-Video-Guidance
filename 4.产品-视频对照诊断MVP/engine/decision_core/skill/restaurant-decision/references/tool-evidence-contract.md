# 工具与证据协议

## 通用返回

所有工具统一返回：

```json
{
  "status": "ok | no_hit | unavailable | forbidden | invalid_input | invalid_result",
  "evidence_ids": ["稳定证据 ID"],
  "data": {},
  "source": "工具、模型或数据版本",
  "error_code": null
}
```

- `ok`：必须同时有 `source` 和至少一个 `evidence_id`。
- `no_hit`：服务成功但没有符合条件的结果；不等于没有风险。
- `unavailable`：超时、网络或服务故障；不得解释为无结果。
- `forbidden`：身份或数据权限不匹配；不得跨用户降级。
- `invalid_input`：参数不全或格式不合法；回到追问或证据动作。
- `invalid_result`：工具声称成功但响应不满足 Schema；不得消费其内容。

外部调用必须由适配器归一化。异常、空字典、非映射返回和 `ok` 但无证据 ID 都不能通过证据门槛。

## 门店档案

`store_profile` 请求必须同时携带已认证 `user_id` 和 `store_id`。只有用户已经确认并正式保存的档案才能返回为：

```json
{
  "status": "ok",
  "evidence_ids": ["profile:store-id:version"],
  "data": {"facts": {"monthly_rent": 6000}},
  "source": "store-profile:version"
}
```

运行时将缺失字段标成 `tool_fact/tool_verified`，但不覆盖当前会话中已有的新事实。模型抽取草稿、待确认字段和其他用户门店不得进入该返回。

## 经营计算

输入使用原子字段：日营业额、每月营业天数、贡献毛利率、月租、月人工、其他月固定成本；在营亏损可附剩余现金。

输出至少包含：

- `monthly_operating_profit_before_tax`
- `break_even_monthly_revenue`
- `break_even_daily_revenue`
- `daily_revenue_gap_to_break_even`
- 可计算时的 `cash_runway_months_at_current_model`
- 未计税费、折旧或需求变化等假设边界

计算结果只证明给定输入下的数学关系，不预测客流、需求和执行效果。

## 现场视觉

至少覆盖正前、左侧、右侧、对面、入口路线和停车/外卖动线。输出必须分开：

```json
{
  "coverage_codes": ["front"],
  "observations": [
    {"observation": "画面直接事实", "frame_locator": "00:12", "confidence": 0.9}
  ],
  "inferences": [
    {
      "inference": "经营解释",
      "supporting_frame_locators": ["00:12"],
      "confidence": 0.7
    }
  ],
  "missing_captures": ["parking"]
}
```

没有画面时间点的观察、没有支持画面的推断或越界置信度均为 `invalid_result`。视觉不得估算未观察到的客流、营业额或顾客意图。

## RAG 命中

每条命中至少包含稳定 `evidence_id`、标题、短摘要、来源链接、来源定位、证据等级和检索模式。

- `golden`：原视频或逐字稿已独立核对，可作决定性案例证据。
- `reviewed`：开发审核的方法卡，可作方法依据。
- `secondary`：二手整理，只作发现线索。
- `draft`：不得用于用户结论。
- `lexical_fallback`：显式降级模式，不能称为语义相似。

历史案例只能支持方法或类比，不能证明当前门店、品牌、商圈或法律事实。

## 私人知识

- 请求必须携带当前已认证 `user_id`。
- 只能返回 `owner_id == user_id` 的条目。
- 缺失或不匹配返回 `forbidden`。
- 不得用平台知识替代用户私人事实，也不得把私人资料写入平台库。

## 最终判断校验

发送给用户前必须校验：

- 结论属于当前 directive 的 `allowed_conclusions`。
- 所有引用 ID 存在于当前会话证据中。
- 决定性证据与反证不重叠。
- 强结论至少包含一项非推断证据。
- 存在冲突标记的事实不能作为决定性证据。
- 第一动作、验证条件和停止条件均非空。


