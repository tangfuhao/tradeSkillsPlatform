## 1. Shared backtest launch logic

- [x] 1.1 Extract or consolidate shared frontend helpers for coverage-aligned default backtest windows and basic start/end validation.
- [x] 1.2 Update existing strategy-page and console callers to consume the shared helpers instead of maintaining duplicated default-window logic.

## 2. Strategy page backtest launcher

- [x] 2.1 Replace the strategy-page one-click "recent 24 hours" confirm flow with a launch surface that captures selected strategy, start time, end time, and initial capital.
- [x] 2.2 Show the local historical coverage range in the launcher and bound the editable inputs to that available window.
- [x] 2.3 Keep a convenience default based on the latest valid 24-hour window without making it the only launch option.

## 3. Validation, copy, and verification

- [x] 3.1 Add strategy-page validation and error messaging for invalid dates, inverted windows, and obvious out-of-coverage selections before calling the backtest API.
- [x] 3.2 Update strategy-page product copy and metrics so they describe a configurable backtest window rather than a fixed 24-hour action.
- [x] 3.3 Verify the strategy page still creates backtests successfully and that invalid windows are rejected consistently with existing backend validation.
