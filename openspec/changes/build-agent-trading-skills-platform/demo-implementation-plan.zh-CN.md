# Demo 实施计划（V0.1 建议稿）

> 历史说明（请以代码为准）
> - 本文保留的是 Demo 开工前的实施计划，很多项目已经实现，部分项目则被替换或延后。
> - 当前代码已经具备 Skill 存储、Envelope 抽取、Backtest Replay、Live Scheduler、Tool Gateway、组合账本模拟和前端展示的基础链路。
> - 仍未落地的方向包括真实通知分发、完整迁移体系、以及更生产化的 worker / 观测能力；如果本文与 `README.md` 或实际代码不一致，请以代码为准。

## 1. 目标

这份文档只回答一个问题：

在不追求高并发、不追求多租户、不追求大规模生产能力的前提下，如何最短路径做出一个能跑通的 Demo？

你的 Demo 需要证明的是：
- 用户提交自然语言 Skill
- 平台能提取 Skill Envelope
- 平台能启动一个 Agent 容器
- Agent 能在回测模式下按节奏重放历史数据
- Agent 能在实时模式下按节奏输出信号
- 最终能看到回测结果或实时通知

## 2. Demo 范围

### 2.1 必须实现
- Skill 存储
- Skill Envelope 抽取
- Agent Runner 容器
- Tool Gateway
- Backtest Replay Driver
- Live Scheduler
- 模拟撮合器
- 结果与信号展示

### 2.2 暂时不做
- 用户体系复杂权限
- 多用户隔离
- 云原生编排
- 真正自动下单
- 高级监控平台
- 多 Agent 协作

## 3. 推荐 Demo 技术栈

- API：FastAPI
- Agent：PydanticAI
- 调度：APScheduler
- 存储：SQLite 或 PostgreSQL
- 历史数据：本地文件 + SQLite/Postgres 索引
- 容器：Docker
- 通知：Telegram 或 Webhook
- 前端：最简单可用的话，先只做 API + 一个极简页面

如果你只想最快验证链路，甚至可以：
- 前端先不做
- 用 Postman / curl / 简单脚本触发

## 4. 目录级模块建议

```text
app/
  api/
  skills/
  envelope/
  agent_runner/
  tool_gateway/
  replay/
  live_scheduler/
  simulation/
  notifications/
  storage/
  models/
```

## 5. 分阶段实施

## Phase 1：跑通最小闭环

目标：
- 只先支持 1 个 Skill
- 只先支持 1 个回测任务
- 只先支持 1 个实时信号任务

### 5.1 Skill 存储
先实现：
- 上传 Markdown Skill
- 保存 Skill 原文
- 生成 `skill_version_id`

### 5.2 Envelope 抽取
先实现：
- 从 Skill 中识别：
  - 名称
  - trigger interval
  - 运行模式
  - 风控约束
  - 是否需要市场扫描
  - 是否需要 Python 执行
- 抽取失败时直接拒绝运行

### 5.3 Tool Gateway 最小版
先实现这几个工具：
- `scan_market`
- `get_candles`
- `get_strategy_state`
- `save_strategy_state`
- `simulate_order`
- `emit_signal`
- `python_exec`

说明：
- `funding_rate` 和 `open_interest` 可以放到第二阶段补
- 如果你当前基础服务已经能提供，就一起加上更好

### 5.4 Agent Runner
先实现：
- 读取 Skill 正文
- 读取 Envelope
- 把工具注册给 Agent
- 要求 Agent 输出固定 JSON schema

### 5.5 回测最小链路
先实现：
- 指定时间范围
- 按 `15m` 或 `4h` 重放
- 每次触发 Agent
- 若 Agent 输出交易动作，交给模拟撮合器
- 最后输出 summary

### 5.6 实时最小链路
先实现：
- APScheduler 每 `15m` 触发一次
- 创建短生命周期 run
- Agent 调实时工具
- 输出结构化信号
- 用 Telegram/Webhook 发出

## Phase 2：补足真实感

### 5.7 补市场扫描能力
增加：
- `get_funding_rate`
- `get_open_interest`
- `get_market_metadata`

### 5.8 补回测展示
增加：
- 收益曲线
- 交易列表
- trace 样本
- 每一步工具调用摘要

### 5.9 补实时状态管理
增加：
- 防重复发信号
- 上次关注标的记录
- 上次信号时间记录

## Phase 3：提高可演示性

### 5.10 Web 页面
最小页面包含：
- 上传 Skill
- 触发回测
- 查看回测结果
- 激活实时策略
- 查看最近信号

### 5.11 运行日志
增加：
- run 列表
- 每个 run 的状态
- Agent 的 reasoning 摘要
- 工具调用轨迹

## 6. Demo 的最小数据要求

为了支撑“山寨币由 Agent 自己判断”，最小数据集建议有：
- USDT 永续合约列表
- 历史 15m / 4h K 线
- 24h 涨跌幅
- 24h 成交额
- 实时 funding rate（如果有）
- 实时 open interest（如果有）

如果一开始拿不到所有项，第一版也可以先只用：
- 合约列表
- K 线
- 24h 涨跌幅
- 成交额

## 7. 回测 Demo 的建议流程

推荐你先验证这个流程：

1. 上传 Skill
2. 系统抽取 Envelope
3. 创建 backtest request
4. 启动回放器
5. 每个 15m 触发 Agent
6. Agent 扫描市场并判断
7. 输出做空/跳过/持有决策
8. 模拟撮合器执行
9. 跑完整段历史
10. 输出 summary + trace

只要这个流程打通，Demo 就已经非常有说服力。

## 8. 实时 Demo 的建议流程

1. 上传 Skill
2. 系统抽取 Envelope
3. 激活 live task
4. APScheduler 到点触发
5. 启动一次 Agent 容器
6. Agent 调实时工具
7. 产出结构化信号
8. Telegram/Webhook 通知用户
9. 保存状态 patch
10. 容器退出

## 9. 你最先应该实现的 8 个 API

按 Demo 目标，我建议优先这 8 个接口：
- `POST /skills`
- `GET /skills/{id}`
- `POST /skills/{id}/extract-envelope`
- `POST /backtests`
- `GET /backtests/{id}`
- `GET /backtests/{id}/summary`
- `POST /live-tasks`
- `GET /live-signals`

## 10. 最小数据库表建议

只做 Demo，最小可以先落这些表：
- `skills`
- `skill_versions`
- `skill_envelopes`
- `backtest_runs`
- `backtest_summaries`
- `live_tasks`
- `live_signals`
- `run_traces`
- `strategy_states`

如果为了快，甚至可以前两阶段用 SQLite。

## 11. 最小容器模型建议

建议至少两个容器：
- `api` 容器：FastAPI + Scheduler
- `agent-runner` 镜像：按需启动的短任务容器

第一版甚至可以偷懒：
- 先不分成真正两套部署
- 先在一个服务里本地模拟“启动 run”
- 等闭环跑通后再拆 Docker

## 12. 一周级别的 Demo 落地顺序建议

如果你想快速推进，我建议按这个顺序：

### Day 1
- Skill 存储
- Envelope 抽取最小版

### Day 2
- Tool Gateway 最小版
- Agent Runner 输出固定 JSON

### Day 3
- Replay Driver
- Sim Executor

### Day 4
- Backtest summary
- trace 存储

### Day 5
- Live Scheduler
- emit_signal

### Day 6
- Telegram/Webhook 通知
- 极简页面或 API 演示脚本

### Day 7
- 联调与演示准备

## 13. Demo 成功的验收标准

只要满足下面 6 条，你的 Demo 就算成功：
- 能上传 Skill Markdown
- 能成功抽取 Skill Envelope
- 能发起一次历史回测
- 回测过程中 Agent 确实每个周期被触发一次
- 能输出回测 summary
- 能启动实时策略并在到点时输出信号通知

## 14. 我对 Demo 实施计划的结论

你现在最需要的不是做全，而是做通。

所以最佳路径不是：
- 一开始就做很强的产品系统

而是：
- 先把 Skill -> Agent -> Tools -> Backtest/Live -> Result 这条最短闭环跑通

只要这条链路打通，你后面无论是加更复杂策略、更多工具，还是更正式的前端与服务化，都有基础可接。
