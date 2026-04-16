# 历史回测全流程说明

本文说明当前代码里，一次“历史回测”如何从前端点击开始，一路执行到 API、Agent Runner、Tool Gateway、历史数据读取、轨迹落盘、组合状态更新和结果汇总。

## 一句话理解

当前历史回测的本质是：

> 在给定历史时间窗内，按照 Skill 的执行节奏逐步推进时间；每到一个触发点，就让 Agent 在“只能看到当时以前数据”的前提下做一次决策；系统再通过当前的组合模拟引擎更新仓位、成交、盈亏和状态，并保存完整轨迹。

它现在更接近：

- `Agent 历史重放 + Tool Gateway 时点约束 + 组合账本模拟 + 轨迹记录`

而不是：

- 完整交易所级别撮合器
- 独立回测任务队列系统
- 带 preview/review 权限边界的回测平台

---

## 1. 入口：前端点击“发起回放”

前端入口：

- `apps/web/src/App.tsx`
- `apps/web/src/api.ts`

核心过程：

1. 用户在前端选择 Skill、时间范围、初始资金
2. 前端检查：
   - 是否已选择 Skill
   - 是否存在本地历史数据覆盖
   - 时间是否合法
3. 前端把时间转换成 UTC 毫秒时间戳：
   - `start_time_ms`
   - `end_time_ms`
4. 调用：

```http
POST /api/v1/backtests
```

请求体示例：

```json
{
  "skill_id": "skill_xxx",
  "start_time_ms": 1689264000000,
  "end_time_ms": 1689265800000,
  "initial_capital": 10000
}
```

说明：

- 传输层统一使用 UTC 毫秒时间戳
- UI 只在展示时转成本地时区时间
- 当前实现没有 preview/review/approved 的额外时间窗限制，是否可运行只看代码里的本地历史覆盖和 cadence 规则

---

## 2. API 创建回测任务

后端入口：

- `apps/api/app/api/routes/backtests.py`
- `apps/api/app/schemas.py`
- `apps/api/app/services/backtest_service.py`

API 收到请求后，会先做“创建 run”，不是立刻同步执行完整回测。

### 创建阶段做的事情

`BacktestService.create_run(...)` 会：

1. 检查 Skill 是否存在
2. 从 Skill Envelope 中读取执行节奏，例如 `15m`
3. 校验 `end_time > start_time`
4. 校验回测窗口是否落在本地历史数据覆盖范围内
5. 校验该窗口是否至少能形成一个完整 cadence 区间
6. 创建一条 `backtest_runs` 记录，初始状态为：
   - `queued`
7. 初始化该 run 对应的：
   - `portfolio_book`
   - `execution_strategy_state`

这一步只是“登记任务 + 初始化执行域”，并不代表回测已经跑完。

---

## 3. 真正执行：FastAPI 后台任务启动回放

创建成功后，API 会返回 `202 Accepted`，同时用 FastAPI 的后台任务启动实际执行：

- `background_tasks.add_task(execute_backtest_job, run["id"])`

这意味着当前实现是：

- 由 API 服务进程自己在后台执行回测
- 不是独立 worker 队列
- 不是消息队列异步消费模式

所以当前方案更适合本地调试和单机 demo。

---

## 4. 回测主循环：按 Skill cadence 生成 trigger 时间点

执行函数：

- `apps/api/app/services/backtest_service.py`

辅助函数：

- `apps/api/app/services/demo_runtime.py`

系统会根据：

- `start_time`
- `end_time`
- `cadence`

生成一组 trigger 时间点。

例如：

- cadence = `15m`
- 窗口 = 30 分钟

则会生成：

1. `00:00`
2. `00:15`
3. `00:30`

整个回测，就是对这些 trigger 逐个执行。

说明：

- 当前实现对 replay step 数量有上限保护
- 如果触发点过多，会截断 replay，并在 summary 里写入 `truncated_replay`

---

## 5. 每一步先构造“当时可见”的市场快照

相关代码：

- `apps/api/app/tool_gateway/demo_gateway.py`
- `apps/api/app/services/market_data_store.py`

每个 trigger 到来后，系统会先为这个时间点构造一个严格的历史市场上下文。

### 关键原则

- 只能读取 `as_of <= 当前 trigger_time` 的数据
- 不允许看到未来数据
- 如果该时刻没有真实历史快照，就直接失败

### 快照中通常包含

- `market_candidates`
- `as_of_ms`
- `provider=historical_db`

`market_candidates` 来自本地 `market_candles` 历史表，系统会基于最近 24 小时数据，为每个 symbol 计算：

- 最新价格
- 24h 涨跌幅
- 24h 成交额
- 简化版 funding / open interest 变化字段

其中 funding 和 open interest 在当前 demo 里仍然是占位性质的补充字段，不是独立实时适配器结果。

---

## 6. API 把这一步交给 Agent Runner

相关代码：

- `apps/api/app/services/backtest_service.py`
- `apps/api/app/services/agent_runner_client.py`

在每个 trigger，API 会组装 payload 发给 Runner：

```json
{
  "skill_id": "...",
  "skill_title": "...",
  "mode": "backtest",
  "trigger_time_ms": 1689264000000,
  "skill_text": "...",
  "envelope": {"...": "..."},
  "context": {
    "market_candidates": ["..."],
    "as_of_ms": 1689264000000,
    "portfolio_summary": {"...": "..."},
    "tool_gateway": {
      "base_url": ".../api/v1/internal/tool-gateway",
      "shared_secret": "...",
      "mode": "backtest",
      "trigger_time_ms": 1689264000000,
      "as_of_ms": 1689264000000,
      "trace_index": 0
    }
  }
}
```

然后调用：

```http
POST /v1/runs/execute
```

也就是说：

- 回测编排者是 API
- 策略推理执行者是 Agent Runner
- Tool Gateway 上下文由 API 显式注入给 Runner

---

## 7. Runner 内部如何做一次 Agent 决策

Runner 相关代码：

- `services/agent-runner/runner/main.py`
- `services/agent-runner/runner/services/decision_engine.py`
- `services/agent-runner/runner/services/openai_runtime.py`

### Runner 收到 payload 后

1. 进入 `OpenAIToolDecisionEngine`
2. 构造一轮运行提示词和工具定义
3. 通过 OpenAI Responses API 进入工具循环
4. 如果模型发起 tool calls，就调用 Tool Gateway 或 Runner 本地工具
5. 工具结果回填给模型
6. 最终返回：
   - `decision`
   - `reasoning_summary`
   - `tool_calls`

### 典型 decision 结构

```json
{
  "action": "open_position",
  "symbol": "LDO-USDT-SWAP",
  "direction": "sell",
  "size_pct": 0.1,
  "reason": "...",
  "stop_loss": { "type": "price_pct", "value": 0.02 },
  "take_profit": { "type": "price_pct", "value": 0.1 },
  "state_patch": {
    "focus_symbol": "LDO-USDT-SWAP"
  }
}
```

### 当前 Runner 的一些实现特点

- 使用的是 Responses API 工具循环，不是旧的 chat-completions 方案
- `compute_indicators`、`python_exec`、`get_portfolio_state` 已经是当前工具集的一部分
- 如果模型最终返回非 JSON，Runner 会 fail-closed 到 `skip`，而不是执行模糊动作

---

## 8. Runner 的工具不是直接查库，而是通过 Tool Gateway 回 API

相关代码：

- `services/agent-runner/runner/services/tool_gateway_client.py`
- `apps/api/app/api/routes/internal_tool_gateway.py`
- `apps/api/app/tool_gateway/market_handlers.py`
- `apps/api/app/tool_gateway/state_handlers.py`
- `apps/api/app/tool_gateway/portfolio_handlers.py`
- `apps/api/app/tool_gateway/signal_handlers.py`

Runner 会把模型请求的工具调用转成 HTTP 请求，再打回 API 的内部 Tool Gateway。

常见工具链路：

- `scan_market` -> `/internal/tool-gateway/market/scan`
- `get_market_metadata` -> `/internal/tool-gateway/market/metadata`
- `get_candles` -> `/internal/tool-gateway/market/candles`
- `get_funding_rate` -> `/internal/tool-gateway/market/funding-rate`
- `get_open_interest` -> `/internal/tool-gateway/market/open-interest`
- `get_strategy_state` -> `/internal/tool-gateway/state/get`
- `save_strategy_state` -> `/internal/tool-gateway/state/save`（兼容接口；当前 Runner 主路径会先本地 stage）
- `get_portfolio_state` -> `/internal/tool-gateway/portfolio/state`
- `simulate_order` -> `/internal/tool-gateway/signal/simulate-order`
- `emit_signal` -> `/internal/tool-gateway/signal/emit`

### 这样设计的意义

- 回测模式和实时模式共用统一工具接口
- 工具层统一控制时间边界
- Agent 不直接接触数据库
- 平台可以把状态、市场、组合、信号意图分层管理

---

## 9. `get_candles` 底层如何读取历史数据

核心代码：

- `apps/api/app/services/market_data_store.py`

### 读取规则

- 如果请求的是基础周期 `1m`
  - 直接读本地历史表
- 如果请求的是更大周期，例如 `15m`、`4h`
  - 先取 `1m` 数据
  - 再在后端聚合成目标周期

因此目前所有技术指标和市场回放，本质上都基于本地 `1m` 历史 K 线。

---

## 10. Agent 返回后，API 如何写状态、组合和轨迹

还是在：

- `apps/api/app/services/backtest_service.py`
- `apps/api/app/services/portfolio_engine.py`

每个 trigger 返回后，系统会做几件事：

### 10.1 应用组合决策

`PortfolioEngine.apply_decision(...)` 会根据动作更新：

- `portfolio_books`
- `portfolio_positions`
- `portfolio_fills`

支持的核心动作包括：

- `open_position`
- `close_position`
- `reduce_position`
- `skip`
- `watch`
- `hold`

### 10.2 保存策略状态 patch

如果 `decision.state_patch` 存在，API 会在本轮 trigger 成功结束时，把它和组合变化一起写入当前 run 对应的执行域状态：

- `execution_strategy_states`

这里不是旧的全局 `strategy_versions` 风格状态模型，而是当前 run / task 作用域下的执行状态。

### 10.3 写一条 trace

每个 trigger 会保存：

- `trace_index`
- `trigger_time`
- `reasoning_summary`
- `decision_json`
- `tool_calls_json`

并在 `trace_execution_details` 里补充：

- `portfolio_before_json`
- `portfolio_after_json`
- `fills_json`
- `mark_prices_json`

这就是前端“执行轨迹”视图的数据来源。

---

## 11. 当前收益和组合状态是怎么计算的

当前版本不再是早期的“单步 close-to-close 简化收益函数”。

现在的核心逻辑是：

1. 在 trigger 时点先对现有持仓做 mark-to-market
2. 如果有交易动作，则按当前可见历史价格执行开仓 / 平仓 / 减仓
3. 更新现金、持仓、已实现盈亏、未实现盈亏
4. 再对组合做一次新的 mark-to-market
5. 结束时根据组合快照和 closed trade 统计构造 summary

summary 当前包含的核心字段包括：

- `realized_pnl`
- `unrealized_pnl_end`
- `net_pnl`
- `total_return_pct`
- `benchmark_return_pct`
- `excess_return_pct`
- `max_drawdown_pct`
- `trade_count`
- `win_rate`
- `fees_paid`
- `final_equity`
- `assumptions`
- `replay_steps`
- `truncated_replay`

### 当前实现仍然是 demo 假设

- `fees_paid` 目前固定为 `0.0`
- funding / open-interest 仍然是简化补充字段
- 组合模拟仍然以历史 close 价格和当前账本规则为主，不是完整撮合微观结构仿真

所以更准确的说法是：

- `组合账本驱动的 demo 级回放引擎`

---

## 12. 回测何时完成，何时失败

### 完成

当所有 trigger 执行完成后，系统会：

- 对最终组合再做一次 mark-to-market
- 计算 closed trade 统计
- 生成 summary
- 把 run 标记为：
  - `completed`

### 失败

如果任意一步失败：

- 当前失败步骤不会写 fake trace
- 已成功步骤保留
- run 被标记为 `failed`
- `error_message` 写入具体 step 和时间

例如：

```text
Backtest step 3 at 2023-07-13T16:30:00+00:00 failed: ...
```

---

## 13. 前端如何看到“执行轨迹”

前端相关逻辑：

- `apps/web/src/App.tsx`

前端会轮询：

- `GET /api/v1/backtests`
- `GET /api/v1/backtests/{run_id}/traces`

当状态是：

- `queued`
- `running`

时，会每隔约 2.5 秒自动刷新一次。

所以你看到的 UI 表现是：

1. 回测先进入队列
2. 状态变成运行中
3. trace 一步步出现
4. 最后 summary 更新

---

## 14. 当前实现最值得记住的特点

### 特点 1：启动方式很轻

- 前端点一次
- API 写 run
- FastAPI 后台任务直接执行

不是独立 worker。

### 特点 2：数据是严格历史数据

- 只用本地历史库
- 通过 `as_of` 和 Tool Gateway 约束未来数据泄漏

### 特点 3：时间传递是 UTC 时间戳

- API / 内部传输统一用毫秒时间戳
- UI 才显示本地时间

### 特点 4：收益和仓位演化已经走组合引擎

- 不再是早期单函数 close-to-close 简化收益模型
- 已经有 run 级组合账本、持仓、fills 和 mark-to-market 流程

### 特点 5：当前没有 preview / review 审核链路

- 回测可否创建只取决于代码中的 Skill 校验、历史覆盖和 cadence 规则
- 不再存在 `preview_ready` / `approved_full_window` 这套边界

---

## 15. 用一句更准确的话定义当前回测系统

当前系统可以定义为：

> 一个按 Skill cadence 驱动的 Agent 历史重放系统。它在每个历史触发点为 Agent 提供当时可见的数据，通过 Tool Gateway 限制未来信息泄漏，用组合账本模拟执行决策，记录完整推理轨迹，并生成基于当前组合状态的回测汇总。

---

## 16. 后续如果要继续增强，通常会往这些方向走

- 引入独立回测 worker，而不是依赖 API 后台任务
- 加入手续费、滑点、资金费等更真实的执行成本
- 增强模拟撮合和风控约束
- 增加更强的失败诊断和可观测性
- 决定 live signal 是否扩展为真实通知通道
