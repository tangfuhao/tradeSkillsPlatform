## Why

The strategy page currently reduces backtest launch to a single "recent 24 hours" action, which is too rigid for real analysis and diverges from the operator console. Users need to choose the replay window themselves, and the available range should reflect the actual local historical coverage so the product surface stays trustworthy.

## What Changes

- Replace the strategy-page one-click "recent 24 hours" backtest action with a configurable launch flow that lets the user choose start time, end time, and initial capital before creating a run.
- Surface the local historical coverage window in the strategy-page launcher and constrain selectable values to that coverage.
- Keep a "recent 24 hours" style default or preset as a convenience, but stop treating it as the only supported window.
- Reuse the same coverage-aware validation rules already enforced by backtest creation so the strategy page and console behave consistently.

## Capabilities

### New Capabilities
- None.

### Modified Capabilities
- `strategy-operations-surface`: strategy management must expose a coverage-aware backtest configuration flow instead of a fixed 24-hour launch action.

## Impact

- Web product UI in the strategy operations surface, including the current strategy action flow and backtest-launch affordances.
- Shared frontend helpers for default backtest windows and historical coverage validation.
- Existing backtest creation API usage, with no new backend contract expected if the current coverage metadata is reused successfully.
