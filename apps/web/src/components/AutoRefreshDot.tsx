import { useEffect, useState } from 'react';

type AutoRefreshDotProps = {
  lastRefreshMs: number | null;
  intervalMs?: number;
};

export default function AutoRefreshDot({ lastRefreshMs, intervalMs = 15000 }: AutoRefreshDotProps) {
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  if (!lastRefreshMs) return null;

  const elapsed = Math.max(0, now - lastRefreshMs);
  const seconds = Math.floor(elapsed / 1000);
  const fresh = elapsed < intervalMs * 0.5;

  return (
    <span className="auto-refresh-dot">
      <span className={`refresh-pulse${fresh ? ' is-fresh' : ''}`} />
      <span className="refresh-label">{seconds < 2 ? '刚刚刷新' : `${seconds}s 前`}</span>
    </span>
  );
}
