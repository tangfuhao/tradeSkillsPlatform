# 文本 Skill 模板规范（V0.1 建议稿）

> 历史说明（请以代码为准）
> - 本文保留的是较强约束的模板建议稿，不等同于当前上传校验规则。
> - 当前代码的最小校验条件以 `apps/api/app/services/envelope_extractor.py` 为准：需要可识别标题、执行 cadence、AI reasoning 段落，以及明确的风险控制/止损信息。
> - 当前实现不会把 Skill 编译成强约束 IR 模板，也没有 `preview -> review -> approved_full_window` 这套后续流转。

## 1. 目标

这份文档定义首版 Agent 交易 Skill 的推荐文本格式，用于满足以下目标：
- 让用户仍然以“文本”提交策略，而不是代码包
- 让平台可以稳定解析、校验、标准化，并编译成可回测的 Strategy IR
- 让策略可解释、可审计、可复现
- 让审核员能快速理解策略意图与风险边界

这不是一个完全自由的自然语言输入框，也不是一个程序员导向的严格 DSL。首版建议采用“固定章节 + 受限规则表达”的半结构化模板。

## 2. 设计原则

### 2.1 用户可写
- 用户写的是文本，不是 Python 或容器
- 允许自然语言描述策略思想
- 但交易规则部分必须使用平台定义的结构化语法

### 2.2 平台可解释
- 平台不能依赖模糊语义执行下单
- 每条入场/出场规则都必须能映射成明确条件和动作
- 不支持的表达必须直接报错，不能静默猜测

### 2.3 回测可复现
- 同一份 skill 文本、同一份数据、同一份参数，必须编译出同一份 Strategy IR
- 回测运行时只执行编译后的 IR，不重复解释原始文本

### 2.4 审核可落地
- 审核员要能快速定位策略市场范围、风险边界、外部依赖、交易频率预期
- Skill 必须显式声明其依赖的数据范围和风险限制

## 3. 首版建议边界

### 3.1 支持的市场
- `market_profile` 固定为 `spot_crypto`

### 3.2 支持的持仓模式
- 首版建议固定为 `long_only`
- 即：只允许空仓和持多仓，不支持做空、借币、杠杆

### 3.3 支持的时间周期
首版建议优先支持：
- `5m`
- `1h`
- `4h`
- `1d`

不建议首版开放 `1m`，原因是：
- 成本高
- 数据量大
- 更容易产生“伪精度”
- 首版文本规则表达也不适合过高频策略

### 3.4 支持的标的范围
- 模板允许 `symbol_scope` 使用数组
- 但首版运行时建议只允许 1 个主交易标的
- 这样可以保持架构可扩展，同时控制 MVP 复杂度

## 4. 文件结构

推荐使用一个文本文件，结构如下：

```md
---
name: <skill-name>
version: <semver>
market_profile: spot_crypto
exchange_scope:
  - <exchange>
symbol_scope:
  - <symbol>
timeframe: <timeframe>
position_mode: long_only
warmup_bars: <integer>
parameters:
  <param_name>:
    type: <integer|number|boolean|string>
    default: <value>
    min: <optional>
    max: <optional>
risk:
  max_position_pct: <0-1>
  max_daily_trades: <integer>
  max_drawdown_pct: <0-1 optional>
---

## Thesis
<自然语言描述策略思想>

## Market Scope
<说明适用市场与前提>

## Entry Rules
### Rule E1
- when: <condition>
- and: <condition>
- then: <action>

## Exit Rules
### Rule X1
- when: <condition>
- then: <action>

## Position Sizing
<说明如何分配仓位>

## Risk Constraints
<说明止损、风控、交易频率限制>

## Invalidations
<说明什么情况下该策略失效>

## Notes
<可选补充>
```

## 5. YAML 元数据规范

### 5.1 必填字段
- `name`: skill 名称，推荐 kebab-case 或 snake_case
- `version`: 版本号，建议语义化版本，例如 `1.0.0`
- `market_profile`: 当前固定为 `spot_crypto`
- `exchange_scope`: 允许的交易所范围，数组
- `symbol_scope`: 允许的标的范围，数组；首版运行时建议仅允许 1 个
- `timeframe`: K 线周期
- `position_mode`: 当前固定为 `long_only`
- `warmup_bars`: 预热 bar 数量

### 5.2 可选字段
- `parameters`: 可调参数定义
- `risk`: 静态风险边界
- `tags`: 可选标签，例如 `trend_following`、`mean_reversion`
- `description`: 简短摘要

### 5.3 参数定义规范
参数统一定义在 `parameters` 下，规则中通过 `$param_name` 引用。

示例：

```yaml
parameters:
  fast_ema:
    type: integer
    default: 20
    min: 5
    max: 100
  slow_ema:
    type: integer
    default: 50
    min: 20
    max: 200
```

### 5.4 风险字段建议
建议支持以下静态风险字段：
- `max_position_pct`: 单次最大仓位占总资金比例
- `max_daily_trades`: 每日最大交易次数
- `max_drawdown_pct`: 若超过阈值则停止开新仓
- `cooldown_bars`: 平仓后冷却 bar 数

## 6. 正文章节规范

### 6.1 `## Thesis`
用途：解释策略的核心思想。

要求：
- 允许自然语言
- 不参与直接执行
- 主要供审核、展示、搜索、理解使用

### 6.2 `## Market Scope`
用途：说明适用市场前提。

要求：
- 说明适用于哪些币对、波动条件或趋势环境
- 不能引用平台未提供的外部数据

### 6.3 `## Entry Rules`
用途：定义何时开仓。

要求：
- 至少 1 条规则
- 每条规则必须以 `### Rule <ID>` 开头
- 每条规则至少 1 个 `when`
- 可选多个 `and` / `or`
- 必须且只能有 1 个 `then`

### 6.4 `## Exit Rules`
用途：定义何时减仓或平仓。

要求与入场规则一致。

### 6.5 `## Position Sizing`
用途：说明仓位分配方式。

首版建议仅允许以下几类表达：
- 固定资金比例
- 固定持仓比例
- 基于账户剩余现金比例

### 6.6 `## Risk Constraints`
用途：定义动态风控。

建议包含：
- 单笔止损
- 单笔止盈
- 最大连续亏损后的暂停
- 冷却期

### 6.7 `## Invalidations`
用途：说明策略在哪些条件下被认为失效。

这部分可以是自然语言，但建议平台从中提取风险标签，作为审核参考，而不是直接作为执行条件。

## 7. 规则表达语法

## 7.1 推荐语法风格
规则部分使用“键值行”表达，而不是长段落。

示例：

```md
### Rule E1
- when: ema(close, $fast_ema) > ema(close, $slow_ema)
- and: close crosses_above ema(close, $fast_ema)
- and: rsi(close, 14) < 65
- then: buy percent_of_cash(0.25)
```

## 7.2 支持的条件类型
首版建议支持以下条件类别：
- 价格比较：`close > sma(close, 20)`
- 交叉事件：`close crosses_above ema(close, 20)`
- 指标比较：`rsi(close, 14) < 30`
- 仓位状态：`position_size == 0`
- 盈亏状态：`unrealized_pnl_pct <= -0.03`
- 时间状态：`bars_since_exit >= 3`

## 7.3 支持的基础字段
- `open`
- `high`
- `low`
- `close`
- `volume`
- `position_size`
- `cash`
- `equity`
- `unrealized_pnl_pct`
- `realized_pnl_pct`
- `bars_since_entry`
- `bars_since_exit`

## 7.4 支持的函数
首版建议支持：
- `sma(series, n)`
- `ema(series, n)`
- `rsi(series, n)`
- `atr(n)`
- `highest(series, n)`
- `lowest(series, n)`

## 7.5 支持的比较与事件操作符
- `>`
- `>=`
- `<`
- `<=`
- `==`
- `!=`
- `crosses_above`
- `crosses_below`

## 7.6 支持的动作
首版建议支持：
- `buy percent_of_cash(x)`
- `buy percent_of_equity(x)`
- `sell percent_of_position(x)`
- `close_position()`
- `hold()`

说明：
- `x` 使用 `0` 到 `1` 的小数表达，例如 `0.25`
- 对于 `long_only` 模式，不支持任何做空动作

## 8. 平台明确不支持的表达

以下类型表达首版应直接校验失败：
- “如果市场看起来偏强就买入”
- “结合社交媒体情绪判断”
- “参考新闻面决定是否卖出”
- “如果我认为风险较高则暂停”
- “使用外部 API 获取链上数据”
- “由大模型实时判断当前走势是否健康”

原因：
- 语义模糊
- 不可复现
- 不利于回测审计
- 超出平台提供的数据边界

## 9. 校验规则

### 9.1 语法校验
- YAML front matter 必须合法
- 必填章节必须存在
- 每个规则块格式必须完整
- 参数引用必须存在

### 9.2 语义校验
- `market_profile` 必须是 `spot_crypto`
- `position_mode` 必须是 `long_only`
- `symbol_scope` 首版运行时只允许 1 个标的
- `warmup_bars` 必须在允许范围内，例如 `0` 到 `2000`
- 时间周期必须在平台支持列表中

### 9.3 策略一致性校验
- 同一条规则不能同时出现冲突动作
- 入场规则不能在 `position_size > 0` 时仍重复满仓买入，除非平台明确支持加仓
- 止损和止盈逻辑不能与静态风险限制矛盾

### 9.4 平台政策校验
- 不允许外部数据依赖
- 不允许未声明的标的
- 不允许暗含人工干预步骤
- 不允许超出平台支持动作集

## 10. 预览与审核策略约束

- skill 上传并通过自动校验后，状态可进入 `preview_ready`
- `preview_ready` 仅允许在最近 90 天窗口内发起回测
- 超出最近 90 天的请求必须进入人工审核
- 审核通过后，skill 可进入 `approved_full_window`

建议的预览窗口产品规则：
- 用户可以自选开始时间和结束时间
- 但开始和结束必须都落在最近 90 天范围内
- 这样比“固定系统窗口”更灵活，也更符合研究习惯

## 11. 推荐完整示例

```md
---
name: btc-ema-pullback
version: 1.0.0
market_profile: spot_crypto
exchange_scope:
  - binance_spot
symbol_scope:
  - BTC/USDT
timeframe: 1h
position_mode: long_only
warmup_bars: 200
parameters:
  fast_ema:
    type: integer
    default: 20
    min: 5
    max: 100
  slow_ema:
    type: integer
    default: 50
    min: 20
    max: 200
risk:
  max_position_pct: 0.5
  max_daily_trades: 3
  cooldown_bars: 2
---

## Thesis
在中期上涨趋势中，等待价格回踩短期均线并重新转强后做多，争取趋势延续收益。

## Market Scope
适用于 BTC/USDT 的 1 小时级别趋势行情，不依赖外部数据。

## Entry Rules
### Rule E1
- when: ema(close, $fast_ema) > ema(close, $slow_ema)
- and: close crosses_above ema(close, $fast_ema)
- and: rsi(close, 14) < 65
- and: position_size == 0
- then: buy percent_of_cash(0.25)

## Exit Rules
### Rule X1
- when: close < ema(close, $fast_ema)
- then: close_position()

### Rule X2
- when: unrealized_pnl_pct <= -0.03
- then: close_position()

## Position Sizing
单次开仓使用账户可用现金的 25%，总仓位不超过账户权益的 50%。

## Risk Constraints
单日最多开 3 次仓位，平仓后冷却 2 根 bar。

## Invalidations
如果 BTC 长期处于高噪音横盘且假突破频繁，策略效果会显著下降。

## Notes
该策略优先追求稳定趋势段，不适合极端消息驱动行情。
```

## 12. 我对首版模板的结论

我建议首版不要做“完全自由文本”，也不要直接做“纯 DSL”。
最适合当前产品阶段的方案是：
- 用户看到的是文本模板
- 平台要求固定章节
- 交易规则使用半结构化语法
- 自然语言只出现在解释性章节，不直接参与执行

这是当前在“用户易用性”和“系统可执行性”之间最平衡的方案。
