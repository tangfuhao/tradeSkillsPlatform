# Strategy IR 设计文档（V0.1 建议稿）

> 历史说明（请以代码为准）
> - 本文描述的是 IR-first 执行路线，但这不是当前代码的运行主路径。
> - 当前实现以原始 Markdown Skill + Skill Envelope + Tool Gateway + OpenAI Responses API 工具循环为核心，不会先把策略编译成确定性的 Strategy IR 再执行。
> - 如果本文和 `services/agent-runner/runner/`、`apps/api/app/services/skills.py`、`apps/api/app/services/envelope_extractor.py` 不一致，请以代码为准。

## 1. 目标

Strategy IR（Intermediate Representation，策略中间表示）是平台内部真正用于执行回测的标准化策略结构。

其核心目的不是给用户看，而是解决 4 个问题：
- 把文本 skill 转成平台可执行的确定性结构
- 保证同一 skill 在同一数据上能稳定复现
- 让策略逻辑能被审核、调试和解释
- 让回测引擎不依赖自然语言解释器逐 bar 执行

## 2. 为什么必须有 IR

如果平台直接在回测过程中解释用户文本，会产生以下问题：
- 同一句话可能被多次解释出不同意思
- 回测成本高，延迟不可控
- 很难解释“为什么这里触发了买入”
- 很难做缓存、测试和差异比较

因此推荐的流程是：

```text
文本 Skill
  -> 语法解析
  -> 语义校验
  -> 规则标准化
  -> Strategy IR
  -> 回测引擎执行
```

这意味着：
- 文本是用户输入层
- IR 是平台执行层
- 二者必须解耦

## 3. 设计原则

### 3.1 确定性
- 同一 skill 文本 + 同一 parser 版本 + 同一参数输入 = 同一 IR
- 同一 IR + 同一数据版本 + 同一回测配置 = 同一结果

### 3.2 可解释
- IR 中每条规则都能映射回原始 skill 中的某个规则块
- 回测结果中的订单和成交，应能追溯到触发它的 rule id

### 3.3 可扩展
- 首版只支持 `spot_crypto` 与 `long_only`
- 但 IR 结构应预留未来扩展空间，例如多标的、组合策略、做空、更多订单类型

### 3.4 可验证
- IR 可以独立做 schema 校验、静态分析和单元测试
- 回测引擎只接受合法 IR

## 4. 编译流程

建议把文本 skill 编译成 IR 的流程拆成 6 步：

### 4.1 Parse
- 解析 YAML front matter
- 识别 Markdown 固定章节
- 提取每个 Rule block

### 4.2 Normalize
- 统一字段命名
- 统一时间周期和 symbol 表达
- 把 `$param_name` 替换为参数引用节点

### 4.3 Validate
- 校验字段完整性
- 校验支持的函数、操作符、动作集合
- 校验市场边界、仓位模式、风险边界

### 4.4 Lowering
- 把文本规则降级为标准表达式树
- 例如把 `ema(close, 20) > ema(close, 50)` 转成 `comparison` 节点

### 4.5 IR Build
- 生成最终 IR JSON
- 为每个规则、条件、动作分配稳定 ID

### 4.6 Report
- 输出 validation report
- 记录 warning、unsupported constructs、normalization notes

## 5. IR 顶层结构

推荐的顶层 JSON 结构：

```json
{
  "schema_version": "strategy_ir.v1",
  "skill_version_id": "sv_123",
  "source_hash": "sha256:...",
  "parser_version": "parser.v1",
  "metadata": {},
  "market": {},
  "parameters": [],
  "indicators": [],
  "rules": [],
  "risk_policy": {},
  "evaluation_plan": {},
  "validation_notes": []
}
```

## 6. 各模块定义

### 6.1 `metadata`
描述 skill 本身的业务信息。

建议字段：
- `name`
- `version`
- `market_profile`
- `timeframe`
- `position_mode`
- `warmup_bars`
- `source_rule_count`

### 6.2 `market`
描述策略可执行的市场边界。

建议字段：
- `exchange_scope`
- `symbol_scope`
- `quote_asset`
- `supported_order_types`

说明：
- 首版 `symbol_scope` 可在 schema 上支持数组
- 但运行校验可限制为长度 1

### 6.3 `parameters`
描述所有运行时参数。

建议结构：

```json
[
  {
    "name": "fast_ema",
    "type": "integer",
    "default": 20,
    "min": 5,
    "max": 100
  }
]
```

### 6.4 `indicators`
描述需要预先计算的指标节点。

建议结构：

```json
[
  {
    "id": "ind_ema_fast",
    "type": "ema",
    "input": "close",
    "period_ref": "$fast_ema"
  },
  {
    "id": "ind_ema_slow",
    "type": "ema",
    "input": "close",
    "period_ref": "$slow_ema"
  }
]
```

作用：
- 避免每条规则重复计算
- 让回测引擎能先构建指标缓存，再执行规则

### 6.5 `rules`
描述所有入场与出场规则。

建议每条规则结构如下：

```json
{
  "id": "rule_entry_e1",
  "kind": "entry",
  "priority": 100,
  "source_ref": "Entry Rules > Rule E1",
  "condition": {},
  "actions": []
}
```

字段建议：
- `id`: 稳定 ID
- `kind`: `entry` 或 `exit`
- `priority`: 数字越小越先执行，或反过来，但必须固定
- `source_ref`: 指向原始 skill 对应位置
- `condition`: 条件表达式树
- `actions`: 动作数组

### 6.6 `condition`
条件统一表示为表达式树，不保留原始自然语言。

支持的节点类型建议包括：
- `comparison`
- `cross_event`
- `logical_all`
- `logical_any`
- `field_ref`
- `indicator_ref`
- `literal`
- `parameter_ref`

示例：

```json
{
  "type": "logical_all",
  "children": [
    {
      "type": "comparison",
      "operator": ">",
      "left": { "type": "indicator_ref", "id": "ind_ema_fast" },
      "right": { "type": "indicator_ref", "id": "ind_ema_slow" }
    },
    {
      "type": "cross_event",
      "operator": "crosses_above",
      "left": { "type": "field_ref", "name": "close" },
      "right": { "type": "indicator_ref", "id": "ind_ema_fast" }
    }
  ]
}
```

### 6.7 `actions`
动作代表策略意图，不等同于最终成交。

建议动作层和撮合层分离。

动作结构示例：

```json
[
  {
    "type": "buy",
    "sizing": {
      "mode": "percent_of_cash",
      "value": 0.25
    }
  }
]
```

首版建议支持的动作：
- `buy`
- `sell`
- `close_position`
- `hold`

说明：
- `buy` / `sell` 是意图
- 能否成交以及成交价格，由回测撮合引擎结合市场规则决定

### 6.8 `risk_policy`
描述静态和动态风控。

建议字段：
- `max_position_pct`
- `max_daily_trades`
- `cooldown_bars`
- `max_drawdown_pct`
- `allow_pyramiding`

首版建议：
- `allow_pyramiding = false`
- 即：不允许加仓叠仓，先降低复杂度

### 6.9 `evaluation_plan`
描述回测引擎执行顺序。

建议字段：
- `evaluate_exit_before_entry: true`
- `apply_risk_gate_before_order_generation: true`
- `position_mode: long_only`
- `benchmark_policy: system_default_in_run_manifest`

这里要特别说明：
- benchmark 不建议写死在 IR 内
- benchmark 属于 run manifest 级配置，因为它与回测窗口、标的、用户选择相关

### 6.10 `validation_notes`
记录非致命 warning，例如：
- 规则可执行，但含有高频交易倾向
- warmup_bars 较大
- 风险限制较弱
- 时间周期与策略描述不一致

## 7. 回测引擎如何使用 IR

建议回测引擎按以下顺序执行：

1. 加载数据版本与 run manifest
2. 加载 Strategy IR
3. 校验 IR schema 版本是否兼容
4. 预计算 warmup 区间内指标缓存
5. 对每个 bar 执行：
   - 更新指标值
   - 先检查风控门
   - 先评估 exit rules
   - 再评估 entry rules
   - 生成 order intents
   - 交给撮合模块模拟成交
   - 更新账户、仓位、资金、日志
6. 输出 summary 与 ledger

建议固定“先出场、后入场”的顺序，避免同一 bar 内歧义。

## 8. 冲突处理规则

首版必须提前定义冲突处理策略，否则回测结果会不稳定。

建议如下：
- 同一时点若多个 exit rule 同时命中：按 `priority` 顺序执行
- 同一时点若多个 entry rule 同时命中：按 `priority` 顺序执行
- 若同一 bar 同时触发 entry 与 exit：先执行 exit
- 若动作与风险规则冲突：风险规则优先
- 若动作与 `long_only` 冲突：直接拒绝该动作并记录 rejection reason

## 9. IR 版本化策略

每一份回测都应该绑定：
- `skill_version_id`
- `strategy_ir.schema_version`
- `parser_version`
- `source_hash`

这样能回答两个关键问题：
- 这次回测到底执行的是哪一版策略结构
- 为什么后来重新上传同名 skill 后，历史结果没有变化

建议：
- 同一个 skill 版本重新编译，若 `source_hash` 不变且 parser 版本不变，IR 应保持不变
- 若 parser 升级，需记录 parser 版本变化，并允许重新验证

## 10. 示例 IR

以下是一个简化示例：

```json
{
  "schema_version": "strategy_ir.v1",
  "skill_version_id": "sv_btc_ema_pullback_1_0_0",
  "source_hash": "sha256:abcd1234",
  "parser_version": "parser.v1",
  "metadata": {
    "name": "btc-ema-pullback",
    "version": "1.0.0",
    "market_profile": "spot_crypto",
    "timeframe": "1h",
    "position_mode": "long_only",
    "warmup_bars": 200,
    "source_rule_count": 3
  },
  "market": {
    "exchange_scope": ["binance_spot"],
    "symbol_scope": ["BTC/USDT"],
    "quote_asset": "USDT",
    "supported_order_types": ["market"]
  },
  "parameters": [
    {
      "name": "fast_ema",
      "type": "integer",
      "default": 20,
      "min": 5,
      "max": 100
    },
    {
      "name": "slow_ema",
      "type": "integer",
      "default": 50,
      "min": 20,
      "max": 200
    }
  ],
  "indicators": [
    {
      "id": "ind_ema_fast",
      "type": "ema",
      "input": "close",
      "period_ref": "$fast_ema"
    },
    {
      "id": "ind_ema_slow",
      "type": "ema",
      "input": "close",
      "period_ref": "$slow_ema"
    }
  ],
  "rules": [
    {
      "id": "rule_exit_x1",
      "kind": "exit",
      "priority": 10,
      "source_ref": "Exit Rules > Rule X1",
      "condition": {
        "type": "comparison",
        "operator": "<",
        "left": { "type": "field_ref", "name": "close" },
        "right": { "type": "indicator_ref", "id": "ind_ema_fast" }
      },
      "actions": [
        {
          "type": "close_position"
        }
      ]
    },
    {
      "id": "rule_entry_e1",
      "kind": "entry",
      "priority": 100,
      "source_ref": "Entry Rules > Rule E1",
      "condition": {
        "type": "logical_all",
        "children": [
          {
            "type": "comparison",
            "operator": ">",
            "left": { "type": "indicator_ref", "id": "ind_ema_fast" },
            "right": { "type": "indicator_ref", "id": "ind_ema_slow" }
          },
          {
            "type": "cross_event",
            "operator": "crosses_above",
            "left": { "type": "field_ref", "name": "close" },
            "right": { "type": "indicator_ref", "id": "ind_ema_fast" }
          }
        ]
      },
      "actions": [
        {
          "type": "buy",
          "sizing": {
            "mode": "percent_of_cash",
            "value": 0.25
          }
        }
      ]
    }
  ],
  "risk_policy": {
    "max_position_pct": 0.5,
    "max_daily_trades": 3,
    "cooldown_bars": 2,
    "allow_pyramiding": false
  },
  "evaluation_plan": {
    "evaluate_exit_before_entry": true,
    "apply_risk_gate_before_order_generation": true,
    "position_mode": "long_only",
    "benchmark_policy": "system_default_in_run_manifest"
  },
  "validation_notes": []
}
```

## 11. 我对 IR 设计的结论

首版最关键的不是把 IR 做得多复杂，而是把边界做清楚：
- 文本层负责表达
- IR 层负责执行
- 回测层只认 IR
- 风控和撮合独立于策略表达

这样以后无论你扩展到：
- 更多市场
- 更多订单类型
- 多标的组合
- 实盘信号执行

都不需要推翻现在的整体架构。
