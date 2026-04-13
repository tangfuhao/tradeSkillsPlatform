# Short-Term Overheat Short Skill

## Execution Cadence
Every 15 minutes.

## Step 1 - Market Scan
Scan OKX USDT perpetual swap instruments and rank candidates by strong short-term upside extension, rising speculative activity, and liquid trading volume.

## Step 2 - Market Data Collection
Fetch 15m and 4h candles for the best candidates and compute EMA20, EMA60, RSI14, and ATR14.
Fetch funding rate and open interest change when available.

## Step 3 - AI Reasoning
You are an AI trading agent.
Reason about which altcoin looks the most overheated for a short setup.
Prefer symbols that recently moved fast, sit far above their short-term trend baseline, and still look crowded on positioning.
If market structure is unclear, skip the cycle.

## Step 4 - Signal Output
If confidence is high, open a short setup with at most 10 percent of equity.
If the signal is weak, emit watch or skip.

## Risk Control
- Every position must define a stop loss at 2 percent.
- Initial take profit target is 10 percent.
- Max daily drawdown is 8 percent.
- Max concurrent positions is 2.
- Hedging is not allowed.
