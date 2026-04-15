import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import ProductStatTile from '../components/ProductStatTile';
import { listLiveTasks, listSignals, listSkills } from '../api';
import {
  countSignalsToday,
  describeAction,
  describeDirection,
  describeStatus,
  formatCount,
  formatPercent,
  formatTime,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildSignalFeed, buildStrategyInsights } from '../lib/product';
import type { LiveSignal, LiveTask, Skill } from '../types';

function signalNarrative(signal: LiveSignal): string {
  return signal.signal.reasoning_summary ?? signal.signal.reason ?? '当前信号没有附带更多说明。';
}

export default function SignalsPage() {
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [nextSignals, nextLiveTasks, nextSkills] = await Promise.all([listSignals(), listLiveTasks(), listSkills()]);

        if (cancelled) return;
        setSignals(nextSignals);
        setLiveTasks(nextLiveTasks);
        setSkills(nextSkills);
        setError(null);
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

  const signalFeed = useMemo(() => buildSignalFeed(signals, liveTasks, skills), [signals, liveTasks, skills]);
  const strategyInsights = useMemo(() => buildStrategyInsights(skills, liveTasks, signals, []), [skills, liveTasks, signals]);
  const activeStrategies = useMemo(
    () => strategyInsights.filter((insight) => insight.signals.length > 0).slice(0, 5),
    [strategyInsights],
  );

  const stats = useMemo(() => {
    const touchedSymbols = new Set(
      signalFeed
        .map((item) => item.signal.signal.symbol?.trim())
        .filter((symbol): symbol is string => Boolean(symbol)),
    );
    const resolvedStrategies = new Set(
      signalFeed
        .map((item) => item.skill?.id)
        .filter((skillId): skillId is string => Boolean(skillId)),
    );
    const activeLiveTasks = liveTasks.filter((task) => task.status === 'active' || task.status === 'running').length;

    return [
      {
        label: 'Signal Feed',
        value: formatCount(signalFeed.length),
        detail: loading ? '正在聚合信号流' : `今日触发 ${formatCount(countSignalsToday(signals))} 条`,
      },
      {
        label: 'Resolved Strategies',
        value: formatCount(resolvedStrategies.size),
        detail: resolvedStrategies.size ? '大部分信号已连回策略档案' : '等待首批策略关联',
      },
      {
        label: 'Active Live Tasks',
        value: formatCount(activeLiveTasks),
        detail: activeLiveTasks ? '当前存在持续触发中的任务' : '暂时没有激活中的实时任务',
      },
      {
        label: 'Symbols In Motion',
        value: formatCount(touchedSymbols.size),
        detail: touchedSymbols.size ? '最近信号已覆盖多个标的' : '等下一条信号进入后开始覆盖',
      },
    ];
  }, [liveTasks, loading, signalFeed, signals]);

  return (
    <div className="product-page-stack">
      <section className="page-header-card neon-panel neon-panel-accent">
        <p className="section-kicker">Signals Deck</p>
        <h1 className="page-title">把实时信号从后台日志，升级成一块可浏览的交易前线。</h1>
        <p className="page-description">
          这里把 live signal、live task 和 strategy profile 串成一条前台可读链路：先看最新动作，再追到触发它的策略，而不是停留在一条原始记录上。
        </p>
        <div className="hero-actions">
          <Link className="neon-button neon-button-primary" to="/strategies">
            浏览策略档案
          </Link>
          <Link className="neon-button neon-button-secondary" to="/console">
            打开 Console
          </Link>
        </div>
      </section>

      <section className="stats-grid">
        {stats.map((stat) => (
          <ProductStatTile key={stat.label} detail={stat.detail} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="neon-banner neon-banner-error">Signals 页面加载失败：{error}</div> : null}

      <section className="content-grid two-column signals-layout-grid">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Live Feed</p>
              <h2>最近的交易动作</h2>
            </div>
            <Link className="inline-link" to="/strategies">
              查看策略目录
            </Link>
          </div>

          <div className="story-list">
            {signalFeed.length ? (
              signalFeed.map((item) => {
                const tone = toneForStatus(item.liveTask?.status ?? item.signal.delivery_status);
                const cadenceLabel = item.liveTask?.cadence ?? item.skill?.envelope.trigger?.value ?? '未解析节奏';
                const symbolLabel = item.signal.signal.symbol ?? '未指定标的';

                return (
                  <article className="story-card static-card signal-feed-card" key={item.signal.id}>
                    <div className="signal-card-head">
                      <div>
                        <small>{describeStatus(item.signal.delivery_status)}</small>
                        <strong>{symbolLabel}</strong>
                      </div>
                      <span className={`tone-pill is-${tone}`}>{cadenceLabel}</span>
                    </div>
                    <p className="signal-card-summary">
                      {describeAction(item.signal.signal.action)} / {describeDirection(item.signal.signal.direction)}
                    </p>
                    <p>{signalNarrative(item.signal)}</p>
                    <div className="tag-row">
                      <span className="meta-chip">{formatTime(item.signal.trigger_time_ms)}</span>
                      {typeof item.signal.signal.size_pct === 'number' ? (
                        <span className="meta-chip">仓位 {formatPercent(item.signal.signal.size_pct)}</span>
                      ) : null}
                      {item.signal.signal.provider ? <span className="meta-chip">{item.signal.signal.provider}</span> : null}
                    </div>
                    <div className="signal-card-footer">
                      {item.skill ? (
                        <Link className="inline-link" to={`/strategies/${item.skill.id}`}>
                          {item.skill.title}
                        </Link>
                      ) : (
                        <span className="muted-label">暂未解析到对应策略</span>
                      )}
                      <span className="muted-label">
                        {item.liveTask ? `任务 ${describeStatus(item.liveTask.status)}` : '等待任务上下文'}
                      </span>
                    </div>
                  </article>
                );
              })
            ) : (
              <div className="empty-product-card wide-empty-card">
                <strong>{loading ? '正在连接实时信号流...' : '信号前线暂时安静'}</strong>
                <p>去 Console 激活实时任务后，这里会形成一条带策略上下文的产品化 signal feed。</p>
                <Link className="neon-button neon-button-secondary" to="/console">
                  前往 Console
                </Link>
              </div>
            )}
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Strategy Context</p>
              <h2>是谁在发出这些信号</h2>
            </div>
            <Link className="inline-link" to="/strategies">
              策略总览
            </Link>
          </div>

          <div className="story-list">
            {activeStrategies.length ? (
              activeStrategies.map((insight) => (
                <Link className="story-card strategy-context-card" key={insight.skill.id} to={`/strategies/${insight.skill.id}`}>
                  <div className="signal-card-head">
                    <div>
                      <small>{describeStatus(insight.skill.validation_status)}</small>
                      <strong>{insight.skill.title}</strong>
                    </div>
                    <span className={`tone-pill is-${toneForStatus(insight.skill.validation_status)}`}>
                      {insight.skill.envelope.trigger?.value ?? '--'}
                    </span>
                  </div>
                  <p>最近信号 {formatCount(insight.signals.length)} 条 / 激活任务 {formatCount(insight.activeTaskCount)} 个</p>
                  <div className="tag-row">
                    {insight.recentSymbols.slice(0, 4).map((symbol) => (
                      <span className="meta-chip" key={symbol}>
                        {symbol}
                      </span>
                    ))}
                    {!insight.recentSymbols.length ? <span className="meta-chip">等待首个交易标的</span> : null}
                  </div>
                  <span className="muted-label">
                    最近触发 {insight.latestSignal ? formatTime(insight.latestSignal.trigger_time_ms) : '暂无 live signal'}
                  </span>
                </Link>
              ))
            ) : (
              <div className="empty-product-card wide-empty-card">
                <strong>还没有策略进入信号态</strong>
                <p>Signals 页已经准备好接策略上下文，只等 live task 被激活并开始产出信号。</p>
              </div>
            )}
          </div>
        </article>
      </section>
    </div>
  );
}
