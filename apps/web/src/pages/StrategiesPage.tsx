import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import ProductStatTile from '../components/ProductStatTile';
import { listBacktests, listLiveTasks, listSignals, listSkills } from '../api';
import {
  describeExtractionMethod,
  describeStatus,
  formatCount,
  formatPercent,
  formatTime,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildStrategyInsights, getSkillCadence, getStrategyExcerpt } from '../lib/product';
import type { BacktestRun, LiveSignal, LiveTask, Skill } from '../types';

function readTotalReturnPct(run: BacktestRun | null): number | null {
  if (!run) return null;
  const value = run.summary?.total_return_pct;
  return typeof value === 'number' ? Number(value) : null;
}

export default function StrategiesPage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [nextSkills, nextLiveTasks, nextSignals, nextBacktests] = await Promise.all([
          listSkills(),
          listLiveTasks(),
          listSignals(),
          listBacktests(),
        ]);

        if (cancelled) return;
        setSkills(nextSkills);
        setLiveTasks(nextLiveTasks);
        setSignals(nextSignals);
        setBacktests(nextBacktests);
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

  const strategyInsights = useMemo(
    () => buildStrategyInsights(skills, liveTasks, signals, backtests),
    [backtests, liveTasks, signals, skills],
  );
  const featuredStrategy = strategyInsights[0] ?? null;

  const stats = useMemo(() => {
    const validatedCount = strategyInsights.filter((insight) => insight.skill.validation_status === 'passed').length;
    const liveLinkedCount = strategyInsights.filter((insight) => insight.liveTasks.length > 0).length;
    const replayLinkedCount = strategyInsights.filter((insight) => insight.backtests.length > 0).length;

    return [
      {
        label: 'Strategies',
        value: formatCount(strategyInsights.length),
        detail: loading ? '正在读取策略目录' : '产品侧可浏览的策略版本数',
      },
      {
        label: 'Validated',
        value: formatCount(validatedCount),
        detail: validatedCount ? '已通过验证的策略可以直接进入体验流' : '等待第一条验证通过的策略',
      },
      {
        label: 'Live-linked',
        value: formatCount(liveLinkedCount),
        detail: liveLinkedCount ? '这些策略已经进入实时信号链路' : '还没有策略连上实时任务',
      },
      {
        label: 'Replay-linked',
        value: formatCount(replayLinkedCount),
        detail: replayLinkedCount ? '已有策略沉淀出历史回放样本' : '回放样本还在形成中',
      },
    ];
  }, [loading, strategyInsights]);

  return (
    <div className="product-page-stack">
      <section className="page-header-card neon-panel">
        <p className="section-kicker">Strategy Library</p>
        <h1 className="page-title">让 Skill 不再只是记录，而是可理解、可追踪、可进入的策略档案。</h1>
        <p className="page-description">
          策略页把 cadence、validation、risk、tooling 和最近执行上下文翻译成产品可读语言。用户先读懂策略，再进入信号与回放，而不是先看一堆 envelope 字段。
        </p>
        <div className="hero-actions">
          <Link className="neon-button neon-button-primary" to={featuredStrategy ? `/strategies/${featuredStrategy.skill.id}` : '/console'}>
            {featuredStrategy ? '打开焦点策略' : '先去创建策略'}
          </Link>
          <Link className="neon-button neon-button-secondary" to="/signals">
            查看实时信号
          </Link>
        </div>
      </section>

      <section className="stats-grid">
        {stats.map((stat) => (
          <ProductStatTile key={stat.label} detail={stat.detail} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="neon-banner neon-banner-error">Strategies 页面加载失败：{error}</div> : null}

      <section className="content-grid two-column strategies-hero-grid">
        <article className="neon-panel neon-panel-accent feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Featured Profile</p>
              <h2>{featuredStrategy?.skill.title ?? '等待首个策略档案'}</h2>
            </div>
            {featuredStrategy ? (
              <Link className="inline-link" to={`/strategies/${featuredStrategy.skill.id}`}>
                进入档案
              </Link>
            ) : null}
          </div>

          {featuredStrategy ? (
            <>
              <p>{getStrategyExcerpt(featuredStrategy.skill)}</p>
              <div className="tag-row">
                <span className={`tone-pill is-${toneForStatus(featuredStrategy.skill.validation_status)}`}>
                  {describeStatus(featuredStrategy.skill.validation_status)}
                </span>
                <span className="meta-chip">节奏 {getSkillCadence(featuredStrategy.skill)}</span>
                <span className="meta-chip">{describeExtractionMethod(featuredStrategy.skill.extraction_method)}</span>
              </div>
              <div className="detail-grid compact-grid">
                <div className="detail-block">
                  <small>实时上下文</small>
                  <strong>{formatCount(featuredStrategy.signals.length)} 条信号</strong>
                  <p>最近触发 {featuredStrategy.latestSignal ? formatTime(featuredStrategy.latestSignal.trigger_time_ms) : '暂无实时动作'}</p>
                </div>
                <div className="detail-block">
                  <small>回放上下文</small>
                  <strong>
                    {readTotalReturnPct(featuredStrategy.latestBacktest) == null
                      ? '等待首条回放'
                      : `收益 ${formatPercent(readTotalReturnPct(featuredStrategy.latestBacktest))}`}
                  </strong>
                  <p>{featuredStrategy.latestBacktest ? `最近 run ${featuredStrategy.latestBacktest.id}` : '该策略还没有回放记录。'}</p>
                </div>
              </div>
            </>
          ) : (
            <div className="empty-product-card wide-empty-card">
              <strong>{loading ? '正在整理策略目录...' : '还没有可浏览的策略档案'}</strong>
              <p>上传或创建第一条 Skill 后，策略页会自动生成产品化的 profile 入口。</p>
              <Link className="neon-button neon-button-secondary" to="/console">
                前往 Console
              </Link>
            </div>
          )}
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Discovery Logic</p>
              <h2>如何阅读一条策略</h2>
            </div>
          </div>
          <div className="flow-list">
            <div className="flow-step">
              <small>01 / Cadence</small>
              <strong>先确认它何时出手</strong>
              <p>先看执行节奏与触发方式，再理解它是偏实时扫描还是偏回放复盘。</p>
            </div>
            <div className="flow-step">
              <small>02 / Risk + Tooling</small>
              <strong>再看它拥有什么边界</strong>
              <p>风险规则和工具限制决定了策略的性格，也决定信号可信度和解释方式。</p>
            </div>
            <div className="flow-step">
              <small>03 / Execution Context</small>
              <strong>最后进入 signals 与 replays</strong>
              <p>看最近 live signal、回放结果和多标的切片，才知道这条策略在市场里怎么表现。</p>
            </div>
          </div>
        </article>
      </section>

      <section className="strategy-grid">
        {strategyInsights.length ? (
          strategyInsights.map((insight) => {
            const latestReturn = readTotalReturnPct(insight.latestBacktest);
            const requiredTools = insight.skill.envelope.tool_contract?.required_tools ?? [];

            return (
              <Link className="story-card strategy-directory-card" key={insight.skill.id} to={`/strategies/${insight.skill.id}`}>
                <div className="signal-card-head">
                  <div>
                    <small>{describeStatus(insight.skill.validation_status)}</small>
                    <strong>{insight.skill.title}</strong>
                  </div>
                  <span className={`tone-pill is-${toneForStatus(insight.skill.validation_status)}`}>
                    {getSkillCadence(insight.skill)}
                  </span>
                </div>
                <p>{getStrategyExcerpt(insight.skill)}</p>
                <div className="detail-grid compact-grid">
                  <div className="detail-block compact-block">
                    <small>Live Signals</small>
                    <strong>{formatCount(insight.signals.length)}</strong>
                    <p>{insight.latestSignal ? formatTime(insight.latestSignal.trigger_time_ms) : '暂无'}</p>
                  </div>
                  <div className="detail-block compact-block">
                    <small>Replay</small>
                    <strong>{latestReturn == null ? '等待样本' : formatPercent(latestReturn)}</strong>
                    <p>{insight.latestBacktest ? insight.latestBacktest.id : '暂无 backtest'}</p>
                  </div>
                </div>
                <div className="tag-row">
                  {(insight.recentSymbols.length ? insight.recentSymbols : requiredTools).slice(0, 4).map((item) => (
                    <span className="meta-chip" key={item}>
                      {item}
                    </span>
                  ))}
                  {!insight.recentSymbols.length && !requiredTools.length ? <span className="meta-chip">等待首条执行上下文</span> : null}
                </div>
                <span className="muted-label">最近活动 {formatTime(insight.lastActivityMs)}</span>
              </Link>
            );
          })
        ) : (
          <div className="empty-product-card wide-empty-card">
            <strong>{loading ? '策略目录加载中...' : '还没有策略可供浏览'}</strong>
            <p>去 Console 创建策略版本后，产品侧会在这里形成可阅读的档案库。</p>
          </div>
        )}
      </section>
    </div>
  );
}
