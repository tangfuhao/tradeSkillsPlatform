import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { listBacktests } from '../api';
import { describeScope, describeStatus, formatTime, getErrorMessage } from '../lib/formatting';
import type { BacktestRun } from '../types';

export default function ReplayHubPage() {
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const nextRuns = await listBacktests();
        if (!cancelled) {
          setBacktests(nextRuns);
          setError(null);
        }
      } catch (nextError) {
        if (!cancelled) {
          setError(getErrorMessage(nextError));
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="product-page-stack">
      <section className="page-header-card neon-panel">
        <p className="section-kicker">Replay Theater</p>
        <h1 className="page-title">挑一条回放，进入多标的 Agent 交易叙事。</h1>
        <p className="page-description">
          这里不再把 backtest 当成一条冷冰冰的记录，而是当成一段可进入的交易剧情：选 run、切 symbol、再逐步看 Agent 为什么动手。
        </p>
      </section>

      {error ? <div className="neon-banner neon-banner-error">回放列表加载失败：{error}</div> : null}

      <section className="replay-card-grid">
        {backtests.length ? (
          backtests.map((run) => {
            const totalReturnPct = typeof run.summary?.total_return_pct === 'number' ? Number(run.summary.total_return_pct) : null;
            return (
              <Link className="replay-card neon-panel" key={run.id} to={`/replays/${run.id}`}>
                <div className="replay-card-head">
                  <small>{describeStatus(run.status)}</small>
                  <span>{describeScope(run.scope)}</span>
                </div>
                <strong>{run.id}</strong>
                <p>{totalReturnPct === null ? '等待汇总' : `总收益 ${(totalReturnPct * 100).toFixed(2)}%`}</p>
                <span>{formatTime(run.created_at_ms)}</span>
              </Link>
            );
          })
        ) : (
          <div className="empty-product-card wide-empty-card">
            <strong>{loading ? '回放列表加载中...' : '还没有可进入的回放'}</strong>
            <p>去 Console 发起第一次历史回放，产品侧就会自动生成可浏览的 theater 入口。</p>
            <Link className="neon-button neon-button-secondary" to="/console">
              前往 Console
            </Link>
          </div>
        )}
      </section>
    </div>
  );
}
