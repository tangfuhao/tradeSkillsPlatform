# Skill Envelope 设计文档（V0.1 建议稿）

## 1. 定位

Skill Envelope 是平台从原始自然语言 Skill 中抽取出的“运行契约”。

它不是传统量化系统中的强确定性策略 IR，也不是对用户策略逻辑的完全编译结果。
它的职责更轻，也更贴合当前产品目标：
- 用户提交的是自然语言 Markdown Skill
- 每次触发时，Agent 仍然会基于最新上下文重新推理
- 平台只需要提前知道“如何运行它”，而不是“替它完全决定交易逻辑”

所以，Skill Envelope 的核心目的只有 5 个：
- 告诉平台这个 Skill 支持什么运行模式
- 告诉平台这个 Skill 需要什么触发节奏
- 告诉平台运行时需要暴露哪些工具
- 告诉平台输出结构应该长什么样
- 告诉平台有哪些不能被突破的硬风控边界

## 2. 为什么不再以 Strategy IR 为中心

此前的思路更接近传统回测平台：
- 用户策略 -> 结构化规则 -> IR -> 回测执行

但你当前真实需求不是这样。
你明确要求：
- Skill 是自然语言
- Skill 必须包含 AI 推理步骤
- Agent 在每个 15 分钟节点都要重新思考
- 回测不要求强可复现
- Agent 可以临时生成脚本辅助分析

这意味着：
- 平台不能假设策略在上传时就能被完全编译为确定性规则
- 平台也不应该试图过度限制 Agent 的推理空间

因此新的设计应改为：

```text
Raw Skill
  -> Skill Envelope
  -> Agent Runtime
  -> Tools + Prompt + Context
  -> Structured Decision
```

在这个模型中：
- Raw Skill = 用户意图本体
- Skill Envelope = 平台运行契约
- Agent Runtime = 实际决策执行体

## 3. Skill Envelope 的边界

Skill Envelope 应包含平台必须提前知道的信息，但不应包含本应由 Agent 动态推理决定的信息。

### 3.1 应包含的内容
- 执行节奏
- 支持模式（回测 / 实时）
- 市场上下文（如 OKX swap）
- 需要的工具清单
- 输出 schema
- 平台硬风控边界
- 状态依赖说明
- 运行资源画像（是否需要 Python 沙箱、是否需要扫描市场）

### 3.2 不应包含的内容
- 某次触发具体应该交易哪个标的
- “山寨币”如何定义
- 当前行情是否属于高位
- 这次是开仓还是跳过
- 是否需要减仓或继续持有

这些都应该由 Agent 在运行时基于工具查询和上下文动态判断。

## 4. Skill Envelope 顶层结构

建议使用 JSON 结构存储。

```json
{
  "schema_version": "skill_envelope.v1",
  "skill_version_id": "skill_ver_123",
  "source_hash": "sha256:...",
  "extracted_at": "2026-04-13T10:00:00Z",
  "runtime_modes": [],
  "trigger": {},
  "market_context": {},
  "tool_contract": {},
  "output_contract": {},
  "risk_contract": {},
  "state_contract": {},
  "runtime_profile": {},
  "extraction_notes": []
}
```

## 5. 字段设计

## 5.1 `runtime_modes`
说明该 Skill 支持哪些模式。

建议值：
- `backtest`
- `live_signal`

示例：

```json
["backtest", "live_signal"]
```

## 5.2 `trigger`
说明触发方式。

示例：

```json
{
  "type": "interval",
  "value": "15m",
  "timezone": "UTC",
  "trigger_on": "bar_close"
}
```

建议字段：
- `type`: 目前首版固定 `interval`
- `value`: 如 `15m`、`4h`
- `timezone`: 统一使用 UTC
- `trigger_on`: `bar_close` / `wall_clock`

我的建议：
- 若 Skill 涉及 K 线判断，默认用 `bar_close`
- 这样无论回测还是实时模式，触发语义都更一致

## 5.3 `market_context`
说明运行市场环境。

示例：

```json
{
  "venue": "okx",
  "instrument_type": "swap",
  "quote_asset": "USDT",
  "scan_scope": "all_usdt_swaps",
  "supports_short": true
}
```

这里特别重要的是：
- 平台不提前规定“山寨币是什么”
- 平台只告诉 Agent 它可以在哪个市场范围里搜索目标

## 5.4 `tool_contract`
说明本 Skill 运行时允许/依赖哪些工具。

示例：

```json
{
  "required_tools": [
    "scan_market",
    "get_candles",
    "get_funding_rate",
    "get_open_interest",
    "get_strategy_state",
    "save_strategy_state",
    "python_exec",
    "emit_signal",
    "simulate_order"
  ],
  "optional_tools": [
    "get_market_metadata"
  ]
}
```

这里的意义是：
- 平台启动容器前就知道要注入哪些工具
- 平台也能提前拒绝“不存在所需工具”的 Skill

## 5.5 `output_contract`
定义 Agent 每次触发必须返回的结构。

示例：

```json
{
  "schema": "trade_signal_v1",
  "required_fields": [
    "action",
    "symbol",
    "direction",
    "size_pct",
    "reason"
  ]
}
```

建议统一支持：
- `skip`
- `watch`
- `open_position`
- `close_position`
- `reduce_position`
- `hold`

说明：
- 回测模式和实时模式都共用这套输出结构
- 回测模式会把输出交给模拟撮合器
- 实时模式会把输出交给通知系统

## 5.6 `risk_contract`
定义平台侧硬约束。

这部分不是替代 Skill 本身的风控，而是平台层的保险丝。

示例：

```json
{
  "max_position_pct": 0.10,
  "requires_stop_loss": true,
  "max_daily_loss_pct": 0.08,
  "max_concurrent_positions": 2,
  "allow_hedging": false
}
```

建议原则：
- Skill 可以更保守
- 平台不允许 Skill 比平台硬约束更激进

## 5.7 `state_contract`
说明这个 Skill 是否依赖外部状态，以及状态由谁持有。

示例：

```json
{
  "stateful": true,
  "state_owner": "base_service",
  "state_access_pattern": [
    "read_before_reasoning",
    "write_after_decision"
  ]
}
```

根据你当前要求，建议固定：
- Agent 自己不持久化长期状态
- 状态全部外置到基础服务

## 5.8 `runtime_profile`
描述运行画像。

示例：

```json
{
  "container_mode": "ephemeral",
  "needs_python_sandbox": true,
  "needs_market_scan": true,
  "reasoning_style": "llm_dynamic",
  "determinism_requirement": "low"
}
```

这部分主要服务于平台调度和资源分配。

## 5.9 `extraction_notes`
记录从自然语言 Skill 抽取 Envelope 时的说明和 warning。

例如：
- 执行节奏明确识别为 `15m`
- Skill 中未明确最大同时持仓数，采用平台默认值 `1`
- Skill 中存在“山寨币”语义，由 Agent 运行时自行解释

## 6. Envelope 抽取流程

建议流程：

```text
Raw Skill Markdown
  -> 结构化标题/章节解析
  -> LLM 辅助抽取
  -> 平台默认值补全
  -> Skill Envelope
  -> 平台校验
```

### 6.1 第一步：结构化解析
先用确定性方法识别：
- 策略名称
- 执行节奏
- 明确写出的风控条款
- 明确写出的工具需求

### 6.2 第二步：LLM 辅助抽取
对自然语言部分做抽取：
- 是否支持回测
- 是否支持实时信号
- 是否依赖市场扫描
- 是否需要 Python 分析能力
- 风险边界是否足够明确

### 6.3 第三步：平台默认值补全
对于未写明但平台必须知道的字段，补默认值。

例如：
- `timezone = UTC`
- `trigger_on = bar_close`
- `requires_stop_loss = true`

### 6.4 第四步：平台校验
若缺失关键运行信息，则拒绝启动。

例如：
- 未识别执行节奏
- 没有任何风控约束
- 输出 schema 无法映射

## 7. 与原始 Skill 的关系

原始 Skill 始终是第一责任文档。
Skill Envelope 只是运行时提取物。

建议保留下面 3 份对象：
- Raw Skill Markdown
- Skill Envelope JSON
- Envelope extraction report

这样有两个好处：
- 方便排查“为什么平台这样调度这个 Skill”
- 方便后续重新抽取 Envelope，而不改原始 Skill

## 8. 与 Agent Prompt 的关系

Skill Envelope 不是给用户看的，也不是最终给 Agent 的全文提示词。

它更适合被系统拿来组装运行时提示：
- 当前模式
- 当前触发时间
- 当前工具列表
- 输出 schema
- 平台硬约束
- 原始 Skill 正文

示意如下：

```text
System Prompt
+ Runtime Context
+ Skill Envelope
+ Raw Skill
+ Tool Access
=> Agent Decision
```

## 9. 示例：做空山寨币策略的 Envelope

下面是一份与你当前需求一致的示例。

```json
{
  "schema_version": "skill_envelope.v1",
  "skill_version_id": "skill_ver_altcoin_short_001",
  "source_hash": "sha256:demo001",
  "extracted_at": "2026-04-13T12:00:00Z",
  "runtime_modes": ["backtest", "live_signal"],
  "trigger": {
    "type": "interval",
    "value": "15m",
    "timezone": "UTC",
    "trigger_on": "bar_close"
  },
  "market_context": {
    "venue": "okx",
    "instrument_type": "swap",
    "quote_asset": "USDT",
    "scan_scope": "all_usdt_swaps",
    "supports_short": true
  },
  "tool_contract": {
    "required_tools": [
      "scan_market",
      "get_candles",
      "get_funding_rate",
      "get_open_interest",
      "get_strategy_state",
      "save_strategy_state",
      "python_exec",
      "emit_signal",
      "simulate_order"
    ],
    "optional_tools": [
      "get_market_metadata"
    ]
  },
  "output_contract": {
    "schema": "trade_signal_v1",
    "required_fields": [
      "action",
      "symbol",
      "direction",
      "size_pct",
      "reason",
      "stop_loss",
      "take_profit"
    ]
  },
  "risk_contract": {
    "max_position_pct": 0.10,
    "requires_stop_loss": true,
    "max_daily_loss_pct": 0.08,
    "max_concurrent_positions": 1,
    "allow_hedging": false
  },
  "state_contract": {
    "stateful": true,
    "state_owner": "base_service",
    "state_access_pattern": [
      "read_before_reasoning",
      "write_after_decision"
    ]
  },
  "runtime_profile": {
    "container_mode": "ephemeral",
    "needs_python_sandbox": true,
    "needs_market_scan": true,
    "reasoning_style": "llm_dynamic",
    "determinism_requirement": "low"
  },
  "extraction_notes": [
    "The term altcoin is left for runtime agent interpretation based on market scan tools.",
    "Short positioning is allowed because instrument_type is swap.",
    "Historical backtest and live signal are both supported."
  ]
}
```

## 10. 校验原则

建议平台对 Skill Envelope 做如下校验：
- 必须识别出触发周期
- 必须识别至少一种运行模式
- 必须识别输出 schema
- 必须识别风险硬约束
- 若 Skill 声明需要扫描市场，则必须存在 `scan_market` 工具
- 若 Skill 允许 Agent 自行写计算脚本，则必须启用 `python_exec`

## 11. 我对 Skill Envelope 的结论

当前系统最适合的中间层不是强规则 IR，而是轻契约 Envelope。

它的价值不在于替代 Agent 推理，而在于让平台知道：
- 怎么调度
- 怎么注入工具
- 怎么限制风险
- 怎么消费输出

对于你当前这个 Demo，这已经足够，而且比做一套复杂 Strategy IR 更贴合真实需求。
