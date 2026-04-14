# Agent 工具清单与运行说明

本文基于当前代码实现整理，不以 `openspec/` 下的历史设计稿为准。

## 1. 文档目的

TradeSkills 当前不是一个多角色协作的 Agent 系统，而是一个统一的交易执行 Agent Runtime：

- 同一份 Skill 可以运行在 `backtest` 和 `live_signal` 两种模式下
- Agent Runner 负责读取 Skill、调用工具、产出结构化决策
- API 侧负责提供 Tool Gateway、维护策略状态、管理组合与落库结果

如果你想快速理解“Agent 到底能用哪些工具、这些工具是怎么工作的、一次运行怎么走完”，这份文档就是面向这个问题写的。

## 2. 当前 Agent 的工具暴露方式

### 2.1 固定标准工具集

当前 Runner 会给模型暴露一套固定标准工具集，而不是根据每份 Skill 的 `tool_contract` 做严格裁剪。

这意味着：

- Skill Envelope 里抽取出的 `required_tools` / `optional_tools` 目前主要用于描述和前端展示
- 真实运行时，模型仍然看到同一套标准工具定义
- 后续如果要做“按 Skill 动态裁剪工具”，需要单独改 Runner 的工具注册逻辑

### 2.2 两类工具来源

当前工具按实现位置分为两类：

1. 远端工具：Runner 通过 API 内部 Tool Gateway HTTP 调用
2. 本地工具：Runner 进程内直接执行，不经过 Tool Gateway

### 2.3 工具总览

| 工具名 | 类型 | 执行位置 | 主要用途 |
| --- | --- | --- | --- |
| `scan_market` | 市场扫描 | API Tool Gateway | 获取当前触发时点的候选市场列表 |
| `get_portfolio_state` | 组合状态 | API Tool Gateway | 读取当前执行范围下的账户、持仓和最近成交 |
| `get_strategy_state` | 策略状态 | API Tool Gateway | 读取当前 Skill 在当前 scope 下的外部化状态 |
| `save_strategy_state` | 策略状态 | API Tool Gateway | 合并并保存状态 patch |
| `get_market_metadata` | 市场信息 | API Tool Gateway | 读取某个候选标的的上下文快照 |
| `get_candles` | 行情 | API Tool Gateway | 获取指定标的与周期的 OHLCV |
| `compute_indicators` | 指标计算 | Runner 本地 | 基于 K 线计算 EMA/SMA/RSI/ATR |
| `get_funding_rate` | 市场补充数据 | API Tool Gateway | 读取当前候选标的的 funding rate 快照 |
| `get_open_interest` | 市场补充数据 | API Tool Gateway | 读取当前候选标的的 open interest 变化快照 |
| `python_exec` | 自定义分析 | Runner 本地 | 运行受限 Python 分析片段 |
| `simulate_order` | 交易意图 | API Tool Gateway | 暂存模拟下单意图，供最终决策复用 |
| `emit_signal` | 信号意图 | API Tool Gateway | 暂存实时信号意图，供最终决策复用 |

## 3. 工具分层理解

### 3.1 API Tool Gateway 工具

这类工具由 API 暴露在 `/api/v1/internal/tool-gateway/*` 下，Runner 会附带当前运行上下文：

- `skill_id`
- `scope_kind`
- `scope_id`
- `mode`
- `trigger_time_ms`
- `as_of_ms`
- `trace_index`

这保证了同一个工具名在回测和实时模式里都能带上统一的执行范围与时间约束。

### 3.2 Runner 本地工具

这类工具在 Runner 内直接执行，主要目的是：

- 减少模型为常见指标计算反复拉原始 candles
- 提供一个轻量的自定义分析沙箱
- 让模型在不扩展 API 的前提下完成临时计算

### 3.3 只读工具缓存

Runner 会对只读工具做参数级缓存，避免同一轮执行里重复请求：

- `scan_market`
- `get_portfolio_state`
- `get_strategy_state`
- `get_market_metadata`
- `get_candles`
- `get_funding_rate`
- `get_open_interest`

这对多轮 tool loop 很重要，因为模型经常会重复读相同上下文。

## 4. 详细工具说明

## 4.1 `scan_market`

**用途**

- 获取当前触发时点可见的候选市场
- 一般是模型的第一步，用于从候选池里挑交易标的

**常见入参**

```json
{
  "top_n": 5,
  "sort_by": "change_24h_pct"
}
```

**返回重点**

- `count`
- `candidates[]`
- `source`
- `as_of_ms`

单个 candidate 当前通常包含：

- `symbol`
- `last_price`
- `change_24h_pct`
- `volume_24h_usd`
- `funding_rate`
- `open_interest_change_24h_pct`
- `is_old_contract`

**当前实现说明**

- 数据源来自本地历史库的市场快照，而不是实时交易所 API
- 快照逻辑会取 `as_of` 之前 24 小时的 `1m` K 线聚合出候选集
- `sort_by` 支持别名，例如 `volume`、`funding`、`oi_change`
- 如果当前时点没有任何候选，会返回 `status = not_available`

**适合什么时候用**

- 先筛选热点标的
- 在多个永续合约里选出最值得进一步分析的对象
- 作为后续 `get_candles` / `compute_indicators` 的入口

## 4.2 `get_portfolio_state`

**用途**

- 读取当前执行范围的组合快照
- 让模型知道当前有没有持仓、最近成交如何、当前浮盈浮亏怎样

**常见入参**

```json
{}
```

**返回重点**

- `portfolio.account`
- `portfolio.positions[]`
- `portfolio.recent_fills[]`

账户摘要一般包括：

- `initial_capital`
- `cash_balance`
- `equity`
- `realized_pnl`
- `unrealized_pnl`
- `total_return_pct`
- `last_mark_time_ms`

**当前实现说明**

- 作用域由 `scope_kind + scope_id` 决定，因此回测和实时任务互不串状态
- 如果 Tool Gateway 带了 `as_of`，API 会先 mark-to-market 再返回快照
- 这个工具非常适合在决定 `hold`、`reduce_position`、`close_position` 前调用

**适合什么时候用**

- 已有仓位时判断是否继续持有
- 需要看 recent fills 判断是否刚开过仓
- 需要看当前权益再决定仓位大小时

## 4.3 `get_strategy_state`

**用途**

- 读取 Skill 的外部化策略状态
- 用来承接“Agent 本身无长期记忆，但系统有状态”这个设计

**常见入参**

```json
{}
```

**返回重点**

```json
{
  "strategy_state": {
    "focus_symbol": "DOGE-USDT-SWAP",
    "last_action": "watch"
  }
}
```

**当前实现说明**

- 状态存在 `execution_strategy_states` 表里
- 状态按 execution scope 存储，不是全局唯一一份
- Runner 在返回给模型前，会把尚未落库的 `pending_state_patch` 也合并进结果

**适合什么时候用**

- 记住上一轮重点关注的 symbol
- 记录防重复发信号标记
- 保存上轮决策阶段性结果，例如 `last_action`、`focus_symbol`

## 4.4 `save_strategy_state`

**用途**

- 保存策略状态 patch
- 让模型把这次运行的阶段性结论外部化

**常见入参**

```json
{
  "patch": {
    "focus_symbol": "WIF-USDT-SWAP",
    "last_action": "watch"
  }
}
```

**返回重点**

- `strategy_state`
- `pending_state_patch`

**当前实现说明**

- 必须传对象类型的 `patch`
- 语义是 merge patch，不是整对象覆盖
- Runner 会先更新本地 `pending_state_patch`，再调用远端保存
- 保存成功后，Runner 还会刷新本地 `get_strategy_state` 缓存
- 即使模型调用了这个工具，最终 JSON 里的 `decision.state_patch` 仍然应该保留相关字段

**适合什么时候用**

- 确认新的观察标的
- 写入上次动作、节奏标记、信号去重标记
- 在最终决策前先稳定记录中间判断

## 4.5 `get_market_metadata`

**用途**

- 读取某个候选标的的上下文快照信息
- 当前更像“候选标的详情”，不是完整交易所规则查询接口

**常见入参**

```json
{
  "market_symbol": "DOGE-USDT-SWAP"
}
```

**返回重点**

- `market_symbol`
- `candidate`
- `as_of_ms`
- `source`
- `mode`

**当前实现说明**

- 会先把 symbol 归一化，例如补上 `-USDT-SWAP`
- 底层还是从当前市场快照里找对应 candidate
- 如果当前时点没有这个 symbol 的候选信息，会返回 `not_available`
- 当前还没有暴露交易规则级字段，比如 `tick_size`、`lot_size`

**适合什么时候用**

- 想确认某个币是否真在当前候选池里
- 想补充读取 candidate 的快照字段
- 作为 `scan_market` 之后的单标的补查工具

## 4.6 `get_candles`

**用途**

- 获取指定标的在指定周期上的 OHLCV
- 是大多数技术分析类判断的基础工具

**常见入参**

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "timeframe": "15m",
  "limit": 120
}
```

**返回重点**

- `market_symbol`
- `timeframe`
- `summary.count`
- `summary.latest_close`
- `summary.window_change_pct`
- `candles[]`

**当前实现说明**

- 底层只长期存 `1m` 基础 K 线
- 如果请求的是更高周期，例如 `15m`、`4h`，会在查询时动态聚合
- 查询是时点安全的：只会返回 `as_of` 之前可见的数据
- 如果没有足够数据，会返回 `not_available`

**适合什么时候用**

- 模型确实需要原始 bar 时
- 需要自定义结构判断，例如连续几根实体大小、影线长度、突破回踩结构
- 需要结合 `python_exec` 做特殊计算时

## 4.7 `compute_indicators`

**用途**

- 快速计算常见指标，避免模型自己重复拉 K 线再人工推导
- 是 `get_candles` 之上的本地便捷工具

**常见入参**

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "timeframe": "15m",
  "limit": 120,
  "ema_periods": [20, 60],
  "rsi_periods": [14],
  "atr_periods": [14]
}
```

**返回重点**

- `market_symbol`
- `timeframe`
- `count`
- `indicators`

例如：

```json
{
  "indicators": {
    "ema_20": 0.214,
    "ema_60": 0.197,
    "rsi_14": 74.3,
    "atr_14": 0.0081
  }
}
```

**当前实现说明**

- 这是 Runner 本地工具，不经 API Tool Gateway 直接暴露
- 但它内部仍会通过 `get_candles` 去拉 K 线
- 支持 `EMA`、`SMA`、`RSI`、`ATR`
- 若没拿到 candles，会返回 `not_available`
- 一般优先推荐用它，而不是上来就用 `python_exec`

**适合什么时候用**

- 技术面筛选
- 趋势对比，如 EMA20 vs EMA60
- 判断超买超卖，如 RSI14
- 评估波动强度，如 ATR14

## 4.8 `get_funding_rate`

**用途**

- 读取某个候选标的的 funding rate 快照
- 主要帮助模型判断市场拥挤程度或做多/做空成本

**常见入参**

```json
{
  "market_symbol": "DOGE-USDT-SWAP"
}
```

**返回重点**

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "funding_rate": 0.0
}
```

**当前实现说明**

- 当前实现还是 demo 级补充字段
- 值来自 market snapshot 中的 candidate 字段
- 而当前 snapshot 默认把 `funding_rate` 填成 `0.0`
- 所以这个工具现在更像占位接口，而不是高可信度的真实交易所 funding 数据

**适合什么时候用**

- 写 prompt 或 Skill 时保留结构位
- 给后续真实 OKX adapter 预留兼容接口
- 在演示中说明“这里未来可以接真实 funding 数据”

## 4.9 `get_open_interest`

**用途**

- 读取某个候选标的的 open interest 变化快照
- 帮助模型判断筹码拥挤和投机强弱

**常见入参**

```json
{
  "market_symbol": "DOGE-USDT-SWAP"
}
```

**返回重点**

```json
{
  "market_symbol": "DOGE-USDT-SWAP",
  "open_interest_change_24h_pct": 0.0
}
```

**当前实现说明**

- 和 `get_funding_rate` 一样，当前属于 demo 级字段
- 值来自 market snapshot 的 candidate 字段
- 当前 snapshot 默认填 `0.0`
- 因此它的接口有用，但数据质量还不是生产级

**适合什么时候用**

- 保留策略结构表达
- 与 future adapter 对齐
- 做产品演示时说明“框架已留好位置”

## 4.10 `python_exec`

**用途**

- 让模型在工具循环里运行一小段自定义 Python 代码
- 适合做内置指标之外的轻量分析

**常见入参**

```json
{
  "description": "check whether the last 5 closes are accelerating",
  "code": "candles = load_candles('DOGE-USDT-SWAP', '15m', 20)\ncloses = [c['close'] for c in candles]\nresult = {'last_5_avg': sum(closes[-5:]) / 5}"
}
```

**返回重点**

- `stdout`
- `result`

**当前实现说明**

- 这是 Runner 本地工具
- 代码长度限制为 6000 字符以内
- 当前明确不允许 `import` 外部模块的工作流，system prompt 也要求不要写 `import`
- 可用内置 helper：
  - `load_candles(symbol, timeframe, limit=None)`
  - `ema(values, period)`
  - `sma(values, period)`
  - `rsi(values, period)`
  - `atr(candles, period)`
- 可用标准对象有限：`math`、`statistics`、`json` 和一小组安全 builtins
- 如果执行异常，会返回错误文本和已产生的 `stdout`

**适合什么时候用**

- 计算非标准组合指标
- 统计最近 N 根 bar 的形态特征
- 快速做一个一次性分析，不值得专门扩展 API 时

## 4.11 `simulate_order`

**用途**

- 暂存一份模拟交易意图
- 帮助模型在最终输出 JSON 前，先把交易决策结构化一下

**常见入参**

```json
{
  "action": "open_position",
  "symbol": "DOGE-USDT-SWAP",
  "direction": "sell",
  "size_pct": 0.1,
  "reason": "Overheated short-term move",
  "stop_loss_pct": 0.02,
  "take_profit_pct": 0.10
}
```

**返回重点**

- `staged_decision`

**当前实现说明**

- 这个工具当前不会直接写成交、不会直接改组合
- 它只是把一个 `staged_decision` 暂存在 Runner 里
- 最终真正执行仍依赖模型最后输出的 `decision`，随后由 API 的 `PortfolioEngine.apply_decision(...)` 落实
- 如果模型没有在最终 JSON 里完整表达决策，单靠这一步并不会成交

**适合什么时候用**

- 模型先把开仓意图成型，再组织最终 JSON
- 需要减少最终 JSON 与中间工具推理之间的偏差时
- 需要把止损止盈参数先结构化时

## 4.12 `emit_signal`

**用途**

- 暂存一份实时信号意图
- 面向 `live_signal` 模式的语义化工具

**常见入参**

```json
{
  "action": "watch",
  "symbol": "DOGE-USDT-SWAP",
  "reason": "Momentum is hot but confirmation is incomplete"
}
```

**返回重点**

- `staged_decision`

**当前实现说明**

- 和 `simulate_order` 一样，它也是 stage，而不是立即外发通知
- 当前项目还没有真实 Telegram / webhook 投递链路
- 最终结果会在 API 侧写入 `live_signals.signal_json`
- 因此它更像“实时模式的意图表达工具”，不是“通知发送工具”

**适合什么时候用**

- `live_signal` 模式下输出 watch / skip / open_position 倾向
- 将实时信号先结构化，再进入最终决策
- 为未来真实通知通道预留接口

## 5. Agent 一次运行的标准流程

下面是当前实现里最典型的一次触发流程。

### 5.1 Step 1：API 准备运行上下文

API 会准备：

- `skill_text`
- `envelope`
- `mode`
- `trigger_time_ms`
- 当前市场候选列表
- 当前组合摘要
- Tool Gateway 上下文

### 5.2 Step 2：Runner 组织 Prompt

Runner 会把这些内容拼进一个统一执行提示：

- Skill 原文
- Envelope
- 压缩市场上下文
- Tool Gateway 摘要
- 当前组合摘要
- 系统规则

### 5.3 Step 3：模型进入 tool loop

模型会在若干轮内反复进行：

1. 选择工具
2. 发起 function call
3. Runner 执行工具
4. 工具结果回传给模型
5. 模型继续判断

### 5.4 Step 4：模型返回最终 JSON

最终必须返回结构化 JSON，至少包括：

- `reasoning_summary`
- `decision.action`
- `decision.symbol`
- `decision.direction`
- `decision.size_pct`
- `decision.reason`
- `decision.stop_loss`
- `decision.take_profit`
- `decision.state_patch`

如果最终不是 JSON，Runner 会 fail closed，默认回退成 `skip`。

### 5.5 Step 5：Runner 做结果清洗

Runner 会做一些统一修正：

- 套用 `risk_contract.max_position_pct`
- 对 `open_position` 自动补默认止损止盈
- 合并 `staged_decision`
- 合并 `pending_state_patch`
- 对某些 action 自动清理无意义字段

### 5.6 Step 6：API 执行与落库

API 收到决策后会：

1. 保存 `state_patch`
2. 通过 `PortfolioEngine` 执行模拟开平仓/减仓/盯市
3. 在回测模式下写入 trace
4. 在实时模式下写入 live signal

## 6. 两个典型案例

## 6.1 案例一：回测中的“过热做空”单轮执行

假设 Skill 的意图是：

- 每 15 分钟扫描 OKX 永续合约
- 找过热币
- 如果确认过热就尝试做空

一轮典型工具序列可能是：

1. `scan_market(top_n=5, sort_by="change_24h_pct")`
2. `compute_indicators(market_symbol="DOGE-USDT-SWAP", timeframe="15m", ema_periods=[20,60], rsi_periods=[14], atr_periods=[14])`
3. `get_strategy_state()`
4. `simulate_order(action="open_position", symbol="DOGE-USDT-SWAP", direction="sell", size_pct=0.1, stop_loss_pct=0.02, take_profit_pct=0.1)`
5. 最终输出 JSON：`open_position + sell + 10%`。

然后 API 会根据该历史时点的可见价格模拟成交，生成 fill，并记录这一步的组合变化和 reasoning。

## 6.2 案例二：实时任务里已有仓位，决定减仓

假设一个 live task 已经持有空单，下一轮触发时：

1. `get_portfolio_state()` 读取当前持仓、浮盈、最近成交
2. `compute_indicators()` 判断短线动能是否开始回落
3. `get_strategy_state()` 看上轮是否已经发过 watch 或 partial take-profit 信号
4. 最终输出 `reduce_position`，`size_pct = 0.5`

这里的 `size_pct = 0.5` 在 `reduce_position` 语义下，表示减掉当前仓位的一半，而不是拿账户权益的 50% 去反向操作。

## 7. 当前实现的限制与注意事项

- `tool_contract` 已抽取，但当前不会严格按 Skill 动态裁剪工具集
- `get_funding_rate` 和 `get_open_interest` 目前是 demo 字段，默认值通常为 `0.0`
- `get_market_metadata` 目前更像候选标的快照，而不是完整交易规则查询接口
- `simulate_order` 和 `emit_signal` 都是意图暂存工具，不会直接触发真实执行或真实通知
- `stop_loss` 和 `take_profit` 当前是决策元数据，不会自动触发平仓
- `live_signal` 当前依赖的是本地最新历史快照，不是交易所 streaming 实时行情
- `python_exec` 虽然实用，但仍应谨慎使用；优先使用 `compute_indicators` 这种更稳定的工具

## 8. 推荐的工具使用顺序

如果你在写 Skill 或给别人讲解系统，推荐把当前 Agent 的工具使用顺序理解成：

1. 先用 `scan_market` 找标的
2. 再用 `compute_indicators` / `get_candles` 看行情结构
3. 用 `get_portfolio_state` 看当前仓位上下文
4. 用 `get_strategy_state` 读历史状态
5. 需要时用 `save_strategy_state` 写状态
6. 在动作成型时用 `simulate_order` 或 `emit_signal` 暂存意图
7. 最后返回结构化 JSON 决策

这样最符合当前 Runner 的 system prompt，也最贴近现有代码的实际运行路径。
