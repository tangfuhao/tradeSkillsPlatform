# 回测平台 API 设计（V0.1 建议稿）

## 1. 目标

这份文档把产品需求继续下沉到接口层，定义首版 Agent 交易 Skills 平台的 API 边界。

设计目标：
- 让前端、后端、审核后台、回测 worker 共享同一套资源模型
- 让“文本 skill -> 自动校验 -> preview -> 人工审核 -> full-history”这条链路能完整落地
- 让接口语义稳定，方便后续扩展到更多市场、更多订单模型和多策略场景

首版建议采用：
- 协议：HTTP + JSON
- 风格：Resource-oriented REST
- 版本：`/api/v1`
- 异步任务：通过资源状态轮询，不强依赖 WebSocket

## 2. 角色与权限

### 2.1 角色
- `author`: 策略作者，上传 skill、发起回测、查看结果、申请审核
- `reviewer`: 审核员，审核 full-history 申请
- `operator`: 运营或数据管理员，管理数据集、查看运行健康
- `admin`: 平台管理员，拥有系统级管理权限

### 2.2 首版权限原则
- 用户只能访问自己的 `strategy`、`strategy_version`、`virtual_account_profile`、`backtest_run`
- `reviewer` 可以访问待审核列表和审核详情
- `operator` 可以管理 `dataset_version` 与质量报告
- `admin` 具有所有权限

## 3. 核心资源模型

首版 API 建议围绕以下资源设计：

| 资源 | 说明 |
|---|---|
| `strategy` | 策略逻辑对象，代表一个策略系列 |
| `strategy_version` | 某次文本提交形成的不可变版本 |
| `validation_report` | 文本 skill 的自动校验结果 |
| `review_request` | 用户申请 full-history 的审核请求 |
| `dataset_version` | 历史数据快照 |
| `virtual_account_profile` | 虚拟账户配置 |
| `backtest_run` | 一次具体回测运行 |
| `run_summary` | 回测摘要指标 |
| `run_ledger` | 回测过程中的订单、成交、事件、仓位、资金日志 |
| `export_bundle` | 导出的结果包 |

## 4. 状态流总览

```text
StrategyVersion
  draft
    -> pending_validation
    -> validation_failed
    -> preview_ready
    -> review_pending
    -> approved_full_window
    -> review_rejected

BacktestRun
  queued
    -> running
    -> completed
    -> failed
    -> cancelled
```

## 5. 通用接口约定

### 5.1 认证
首版建议：
- 用户端使用 Bearer Token 或 Cookie Session
- 所有写接口都需要认证
- 审核与运营接口需要服务端基于角色做 RBAC 校验

### 5.2 幂等性
所有会创建资源的 POST 接口建议支持：
- 请求头：`Idempotency-Key`

适用场景：
- 创建 strategy version
- 创建 review request
- 创建 backtest run
- 创建 export bundle

### 5.3 分页
列表接口建议统一支持：
- `limit`
- `cursor`
- `sort`

返回建议统一为：

```json
{
  "items": [],
  "next_cursor": "cursor_xxx"
}
```

### 5.4 时间格式
统一使用 ISO 8601 UTC 时间，例如：
- `2026-04-13T09:30:00Z`

### 5.5 错误格式
统一错误结构建议：

```json
{
  "error": {
    "code": "preview_window_exceeded",
    "message": "Strategy version is not eligible for the requested date range.",
    "details": {
      "allowed_window_start": "2026-01-13T00:00:00Z",
      "allowed_window_end": "2026-04-13T23:59:59Z"
    },
    "request_id": "req_123"
  }
}
```

## 6. 用户端 API 设计

## 6.1 Strategy 系列

### `POST /api/v1/strategies`
用途：创建一个新的策略逻辑对象，并可同时提交首个文本版本。

请求体建议：

```json
{
  "name": "btc-ema-pullback",
  "description": "Trend-following strategy for BTC/USDT.",
  "initial_version": {
    "source_text": "---\nname: btc-ema-pullback\nversion: 1.0.0\n..."
  }
}
```

返回：
- `201 Created`
- 返回 `strategy` 基础信息和首个 `strategy_version`

### `GET /api/v1/strategies`
用途：获取当前用户的策略列表。

支持过滤：
- `status`
- `name`
- `market_profile`

### `GET /api/v1/strategies/{strategy_id}`
用途：获取单个策略详情，包括最新版本摘要。

### `POST /api/v1/strategies/{strategy_id}/versions`
用途：为某个策略创建新版本。

请求体建议：

```json
{
  "source_text": "---\nname: btc-ema-pullback\nversion: 1.0.1\n...",
  "change_note": "Tighten stop-loss and reduce overtrading."
}
```

关键规则：
- 新版本创建后进入 `pending_validation`
- 不覆盖旧版本已有回测结果

### `GET /api/v1/strategies/{strategy_id}/versions`
用途：查看某个策略的版本列表。

### `GET /api/v1/strategy-versions/{strategy_version_id}`
用途：查看单个版本详情。

建议返回字段：
- `status`
- `validation_status`
- `review_status`
- `source_text`
- `parsed_metadata`
- `ir_version`
- `preview_eligibility`
- `created_at`

### `GET /api/v1/strategy-versions/{strategy_version_id}/validation-report`
用途：查看自动校验报告。

建议返回：
- 语法错误
- 语义错误
- warning
- normalization notes
- parser version
- source hash

### `GET /api/v1/strategy-versions/{strategy_version_id}/preview-window`
用途：告诉前端当前版本在当前时间点可合法运行的 preview 窗口。

返回示例：

```json
{
  "scope": "preview_only",
  "window_start": "2026-01-13T00:00:00Z",
  "window_end": "2026-04-13T23:59:59Z",
  "can_request_full_history_review": true
}
```

说明：
- 这里的 90 天窗口由服务端按当前日期动态计算
- 例如在 2026-04-13 发起请求时，默认 preview 窗口约束为 2026-01-13 到 2026-04-13

## 6.2 Review Request 系列

### `POST /api/v1/strategy-versions/{strategy_version_id}/review-requests`
用途：用户申请更大的历史测试窗口。

请求体建议：

```json
{
  "requested_start": "2024-01-01T00:00:00Z",
  "requested_end": "2026-04-13T00:00:00Z",
  "reason": "Need to validate across multiple market regimes."
}
```

关键校验：
- 只有 `preview_ready` 的版本可以发起
- 同一版本若已有 `review_pending` 请求，禁止重复申请

### `GET /api/v1/review-requests`
用途：用户查看自己提交的审核请求。

### `GET /api/v1/review-requests/{review_request_id}`
用途：查看某个审核请求详情与审核结论。

## 6.3 Virtual Account 系列

### `POST /api/v1/virtual-account-profiles`
用途：创建虚拟账户配置。

请求体建议：

```json
{
  "name": "default-usdt-10k",
  "base_currency": "USDT",
  "initial_equity": 10000,
  "fee_profile": {
    "mode": "bps",
    "maker_bps": 10,
    "taker_bps": 10
  },
  "slippage_profile": {
    "mode": "fixed_bps",
    "value": 5
  }
}
```

### `GET /api/v1/virtual-account-profiles`
用途：查看当前用户的虚拟账户配置列表。

### `GET /api/v1/virtual-account-profiles/{profile_id}`
用途：查看单个虚拟账户配置。

### `PATCH /api/v1/virtual-account-profiles/{profile_id}`
用途：修改默认账户配置。

说明：
- 建议只允许修改未被固定到历史 run manifest 的可变字段
- 对已被 run manifest 使用的配置，实际回测时应保留 manifest 快照，不回溯修改

## 6.4 Backtest Run 系列

### `POST /api/v1/backtest-runs`
用途：创建一次回测任务。

请求体建议：

```json
{
  "strategy_version_id": "sv_123",
  "dataset_version_id": "dv_456",
  "virtual_account_profile_id": "vap_789",
  "requested_window": {
    "start": "2026-03-01T00:00:00Z",
    "end": "2026-04-13T00:00:00Z"
  },
  "parameter_overrides": {
    "fast_ema": 18,
    "slow_ema": 55
  },
  "benchmark": null,
  "notes": "Preview run before requesting approval."
}
```

服务端行为建议：
- 校验 `strategy_version` 当前状态
- 校验所选时间窗是否落在 preview 或 full-history 许可范围内
- 若 `benchmark = null`，自动生成默认 benchmark
- 生成 immutable `run_manifest`
- 创建 `backtest_run`，初始状态为 `queued`

### `GET /api/v1/backtest-runs`
用途：查看当前用户的回测任务列表。

建议过滤条件：
- `status`
- `strategy_version_id`
- `scope` (`preview` / `approved_full_history`)
- `created_after`
- `created_before`

### `GET /api/v1/backtest-runs/{run_id}`
用途：查看 run 的基本详情与状态。

建议返回：
- `status`
- `scope`
- `run_manifest`
- `summary_available`
- `failure_reason`
- `created_at`
- `started_at`
- `completed_at`

### `GET /api/v1/backtest-runs/{run_id}/summary`
用途：获取回测摘要指标。

建议返回字段：
- `net_pnl`
- `total_return_pct`
- `benchmark_return_pct`
- `excess_return_pct`
- `max_drawdown_pct`
- `trade_count`
- `win_rate_pct`
- `fees_paid`
- `scope_label`
- `trust_warnings`

### `GET /api/v1/backtest-runs/{run_id}/manifest`
用途：查看不可变运行清单。

建议返回：
- strategy version 引用
- parser version
- strategy ir version
- dataset version
- benchmark policy
- fee/slippage profile snapshot
- preview/full-history scope

### `GET /api/v1/backtest-runs/{run_id}/orders`
### `GET /api/v1/backtest-runs/{run_id}/fills`
### `GET /api/v1/backtest-runs/{run_id}/events`
### `GET /api/v1/backtest-runs/{run_id}/positions`
### `GET /api/v1/backtest-runs/{run_id}/equity-curve`
用途：分块拉取回测细节数据，避免一个 summary 接口塞入全部细节。

共同建议：
- 支持分页
- 支持时间范围过滤
- 支持导出前预览

### `POST /api/v1/backtest-runs/{run_id}/cancel`
用途：取消排队中或运行中的回测。

规则：
- 仅 `queued` 或 `running` 可取消
- 取消后进入 `cancelled`

### `POST /api/v1/backtest-runs/{run_id}/rerun`
用途：基于历史 run manifest 重新创建一个新任务。

规则：
- 默认复用相同 manifest
- 也可允许只替换 `dataset_version_id` 或参数，形成派生 run
- 若发生替换，应明确标记为新的 manifest，而不是覆盖旧 run

## 6.5 Export 系列

### `POST /api/v1/backtest-runs/{run_id}/exports`
用途：创建结果导出包。

请求体建议：

```json
{
  "format": "json_zip",
  "include": ["summary", "manifest", "orders", "fills"]
}
```

### `GET /api/v1/backtest-runs/{run_id}/exports`
用途：查看导出记录列表。

### `GET /api/v1/exports/{export_id}`
用途：获取导出任务详情与下载地址。

## 7. 审核后台 API 设计

## 7.1 Review Queue

### `GET /api/v1/admin/review-requests`
用途：审核员查看待审核列表。

支持过滤：
- `status=pending`
- `market_profile=spot_crypto`
- `requested_window_start`
- `strategy_version_status`

### `GET /api/v1/admin/review-requests/{review_request_id}`
用途：查看审核详情。

建议附带：
- 原始文本 skill
- validation report
- preview runs 概览
- 用户申请的时间范围
- 数据集覆盖能力

### `POST /api/v1/admin/review-requests/{review_request_id}/approve`
用途：审核通过。

请求体建议：

```json
{
  "approved_window_start": "2024-01-01T00:00:00Z",
  "approved_window_end": "2026-04-13T00:00:00Z",
  "comment": "Validated against template and preview performance."
}
```

服务端行为：
- review request -> `approved`
- strategy version -> `approved_full_window`
- 记录 reviewer、comment、时间戳

### `POST /api/v1/admin/review-requests/{review_request_id}/reject`
用途：审核拒绝。

请求体建议：

```json
{
  "reason_code": "insufficient_risk_disclosure",
  "comment": "Need clearer invalidation rules and risk controls."
}
```

服务端行为：
- review request -> `rejected`
- strategy version -> `review_rejected`
- 保留该版本的 preview 运行资格

我的建议：
- 被拒绝后，版本仍然保留 preview 能力
- 因为拒绝的是 full-history 扩权，而不是否定其 preview 合法性
- `review_rejected` 表达的是审核结论，`preview` 资格表达的是执行范围，这两者不应混为同一个语义

## 7.2 Dataset 管理

### `POST /api/v1/admin/dataset-versions`
用途：创建数据集版本记录并触发导入。

### `GET /api/v1/admin/dataset-versions`
用途：查看数据集列表。

### `GET /api/v1/admin/dataset-versions/{dataset_version_id}`
用途：查看数据集详情。

### `GET /api/v1/admin/dataset-versions/{dataset_version_id}/quality-report`
用途：查看数据质量报告。

### `POST /api/v1/admin/dataset-versions/{dataset_version_id}/publish`
用途：将数据集版本标记为可用于回测。

### `POST /api/v1/admin/dataset-versions/{dataset_version_id}/deprecate`
用途：下线数据集版本，禁止新 run 继续使用。

## 8. 关键资源返回示例

## 8.1 `strategy_version`

```json
{
  "id": "sv_123",
  "strategy_id": "st_001",
  "version": "1.0.1",
  "status": "preview_ready",
  "market_profile": "spot_crypto",
  "timeframe": "1h",
  "symbol_scope": ["BTC/USDT"],
  "parser_version": "parser.v1",
  "source_hash": "sha256:abcd1234",
  "created_at": "2026-04-13T10:00:00Z"
}
```

## 8.2 `backtest_run`

```json
{
  "id": "run_123",
  "strategy_version_id": "sv_123",
  "dataset_version_id": "dv_456",
  "virtual_account_profile_id": "vap_789",
  "status": "running",
  "scope": "preview",
  "benchmark_policy": "system_default_buy_and_hold",
  "requested_window": {
    "start": "2026-03-01T00:00:00Z",
    "end": "2026-04-13T00:00:00Z"
  },
  "created_at": "2026-04-13T10:05:00Z",
  "started_at": "2026-04-13T10:05:10Z",
  "completed_at": null
}
```

## 9. 建议的 HTTP 状态码

- `200 OK`: 查询成功
- `201 Created`: 创建成功
- `202 Accepted`: 异步任务已受理
- `400 Bad Request`: 参数格式错误
- `401 Unauthorized`: 未认证
- `403 Forbidden`: 无权限
- `404 Not Found`: 资源不存在
- `409 Conflict`: 状态冲突，例如重复 review request
- `422 Unprocessable Entity`: 业务规则不满足，例如 preview 窗口越界
- `429 Too Many Requests`: 频率限制

## 10. 两个最重要的接口设计决策

### 10.1 预览窗口校验必须在 `POST /backtest-runs` 做服务端强校验
原因：
- 前端只是辅助，不能承担规则正确性
- preview 是平台风险边界，不应靠客户端约束

### 10.2 不把所有信息塞进一个 run detail 接口
原因：
- 回测 ledger 可能很大
- summary 和明细的读取频率差异很大
- 前端页面通常也是分块加载

## 11. 我对 API 设计的结论

首版最重要的是把 3 条链路打通：
- 文本 strategy version 提交链路
- preview / review / approved 的权限链路
- 回测 run / summary / ledger / export 的结果链路

只要这 3 条链路设计稳定，后续无论你加：
- WebSocket 推送
- 多标的组合
- 参数寻优
- 实盘信号下发

API 都不需要推倒重来。
