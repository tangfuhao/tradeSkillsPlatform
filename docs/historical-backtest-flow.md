# 历史回测全流程说明

本文说明当前代码里，一次“历史回测”是如何从前端点击，一路执行到 Agent Runner、Tool Gateway、历史数据读取、轨迹落盘和收益汇总的。

## 一句话理解

当前历史回测的本质是：

> 在给定历史时间窗内，按照 Skill 的执行节奏逐步推进时间；每到一个触发点，就让 Agent 在“只能看到当时以前数据”的前提下做一次决策；系统再记录轨迹并用简化规则计算收益。

它目前更接近：

- `Agent 历史重放 + 轨迹记录 + 简化收益结算`

而不是一个完整的交易所级撮合回测器。

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

- 数据传输层统一用 UTC 时间戳
- 只有 UI 展示时才转成本地时区时间

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
2. 从 Skill envelope 中读取执行节奏，例如 `15m`
3. 校验回测窗口是否合法
4. 校验回测窗口是否落在本地历史数据覆盖范围内
5. 校验该窗口是否至少能形成一个完整 cadence 区间
6. 写入一条 `backtest_runs` 记录，初始状态为：

- `queued`

这一步只是“登记任务”，并不代表回测已经跑完。

---

## 3. 真正执行：FastAPI 后台任务启动回放

创建成功后，API 会立刻返回 `202 Accepted`，同时用 FastAPI 的后台任务启动实际执行：

- `background_tasks.add_task(execute_backtest_job, run["id"])`

这意味着当前实现是：

- 由 API 服务进程自己在后台执行回测
- 不是独立 worker 队列
- 不是消息队列异步消费模式

所以现在的运行方式更适合开发和验证。

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

则会生成 3 个触发点：

1. `00:00`
2. `00:15`
3. `00:30`

后面整个回测，就是对这些 trigger 逐个执行。

---

## 5. 每一步先构造“当时可见”的市场快照

相关代码：

- `apps/api/app/tool_gateway/demo_gateway.py`
- `apps/api/app/services/market_data_store.py`

每个 trigger 到来后，系统先为这个时间点构造一个严格的历史市场上下文。

### 这里的关键原则

- 只能读取 `as_of <= 当前 trigger_time` 的数据
- 不允许看到未来数据
- 不允许 synthetic fallback
- 如果该时刻没有真实历史快照，就直接失败

### 快照中通常包含

- `market_candidates`
- `as_of_ms`
- `provider=historical_db`

`market_candidates` 来自本地 `market_candles` 历史表，系统会基于最近 24 小时数据，为每个 symbol 计算：

- 最新价格
- 24h 涨跌幅
- 24h 成交额
- 其他简化字段

---

## 6. API 把这一步交给 Agent Runner

相关代码：

- `apps/api/app/services/backtest_service.py`
- `apps/api/app/services/agent_runner_client.py`

在每个 trigger，API 会组装一份 payload 发给 Runner：

```json
{
  "skill_id": "...",
  "skill_title": "...",
  "mode": "backtest",
  "trigger_time_ms": 1689264000000,
  "skill_text": "...",
  "envelope": { "...": "..." },
  "context": {
    "market_candidates": [ "..."],
    "as_of_ms": 1689264000000,
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

- 回测执行者是 API
- 策略推理执行者是 Agent Runner

---

## 7. Runner 内部如何做一次 Agent 决策

Runner 相关代码：

- `services/agent-runner/runner/main.py`
- `services/agent-runner/runner/services/decision_engine.py`
- `services/agent-runner/runner/services/openai_runtime.py`

### Runner 收到 payload 后

1. 进入 `OpenAIToolDecisionEngine`
2. 构造 prompt/messages
3. 调用模型
4. 如果模型发起 tool calls，就进入工具调用循环
5. 工具结果回填给模型
6. 最终返回：
   - `decision`
   - `reasoning_summary`
   - `tool_calls`

### decision 的典型结构

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

---

## 8. Runner 的工具不是直接查库，而是通过 Tool Gateway 回 API

相关代码：

- `services/agent-runner/runner/services/tool_gateway_client.py`
- `apps/api/app/api/routes/internal_tool_gateway.py`
- `apps/api/app/tool_gateway/market_handlers.py`

Runner 会把模型请求的工具调用转成 HTTP 请求，再打回 API 的内部 Tool Gateway。

常见工具链路：

- `scan_market` -> `/internal/tool-gateway/market/scan`
- `get_candles` -> `/internal/tool-gateway/market/candles`
- `get_strategy_state` -> `/internal/tool-gateway/state/get`
- `save_strategy_state` -> `/internal/tool-gateway/state/save`

### 这样设计的意义

- 回测模式和实时模式共用统一工具接口
- 工具层能统一控制时间边界
- 避免 Agent 直接接触数据库

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

## 10. Agent 返回后，API 如何写轨迹和更新状态

还是在：

- `apps/api/app/services/backtest_service.py`

每个 trigger 返回后，系统会做三件事：

### 10.1 保存策略状态

如果 `decision.state_patch` 存在，就写入 `strategy_states`

### 10.2 写一条 trace

trace 会保存：

- `trace_index`
- `trigger_time`
- `reasoning_summary`
- `decision_json`
- `tool_calls_json`

这就是你在前端“执行轨迹”里看到的内容来源。

### 10.3 更新收益

当前收益计算是简化版，只在以下情况下触发：

- `decision.action == "open_position"`

---

## 11. 当前收益是怎么计算的

收益计算函数：

- `apps/api/app/services/backtest_service.py::_compute_trade_return_from_history`

当前逻辑非常重要：

1. 用当前 trigger 时刻的 `1m close` 作为入场价
2. 用下一个 trigger 时刻的 `1m close` 作为离场价
3. 如果方向是 `sell`，收益取反
4. 把这一步收益乘到 equity 上

公式可近似理解为：

```text
raw_return = (exit_close - entry_close) / entry_close
if direction == "sell":
    raw_return = -raw_return
equity = equity * (1 + raw_return)
```

### 当前版本没有计算

- 手续费
- 滑点
- 资金费

### 当前版本也不是完整持仓引擎

它没有完整模拟：

- 持仓簿
- 加仓/减仓生命周期
- 真正的平仓撮合
- 多笔仓位并存账户演化

所以目前更准确的说法是：

- `trigger-based 简化收益评估`

而不是完整交易回测撮合器。

---

## 12. 回测何时完成，何时失败

### 完成

当所有 trigger 都执行完成后，系统汇总：

- `net_pnl`
- `total_return_pct`
- `benchmark_return_pct`
- `max_drawdown_pct`
- `trade_count`
- `win_rate`
- `final_equity`

然后把 run 标记为：

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
- 不再使用 synthetic fallback

### 特点 3：时间传递是 UTC 时间戳

- API/内部传输统一用毫秒时间戳
- UI 才显示本地时间

### 特点 4：收益模型是简化版

- 只对 `open_position` 做当前 trigger 到下一 trigger 的收益结算
- 不是完整持仓/撮合回测引擎

---

## 15. 用一句更准确的话定义当前回测系统

当前系统可以定义为：

> 一个按 Skill cadence 驱动的 Agent 历史重放系统。它在每个历史触发点为 Agent 提供当时可见的数据，通过 Tool Gateway 限制未来信息泄漏，记录完整推理轨迹，并以简化的 close-to-close 规则生成收益汇总。

---

## 16. 后续如果要继续增强，通常会往这些方向走

- 引入独立回测 worker，而不是依赖 API 后台任务
- 引入真实持仓簿和订单生命周期
- 支持 `open_position / hold / reduce_position / close_position` 的完整账户演化
- 加入手续费、滑点、资金费
- 引入更真实的撮合和风控约束
- 增加更强的失败诊断和可观测性

