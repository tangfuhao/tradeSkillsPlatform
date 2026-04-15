import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import ProductStatTile from '../components/ProductStatTile';
import { getMarketOverview, listBacktests, listLiveTasks, listSignals, listSkills } from '../api';
import {
  countSignalsToday,
  describeAction,
  describeDirection,
  describeStatus,
  formatCount,
  formatTime,
  getErrorMessage,
} from '../lib/formatting';
import { buildSignalFeed, buildStrategyInsights, getSkillCadence, getStrategyExcerpt } from '../lib/product';
import type { BacktestRun, LiveSignal, LiveTask, MarketOverview, Skill } from '../types';

function readTotalReturnText(run: BacktestRun | null): string {
  if (!run) return '等待第一次回放';
  const value = run.summary?.total_return_pct;
  return typeof value === 'number' ? `总收益 ${(Number(value) * 100).toFixed(2)}%` : '等待汇总结果';
}

export default function ProductHomePage() {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [overview, setOverview] = useState<MarketOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      try {
        const [nextSkills, nextBacktests, nextSignals, nextLiveTasks, nextOverview] = await Promise.all([
          listSkills(),
          listBacktests(),
          listSignals(),
          listLiveTasks(),
          getMarketOverview(),
        ]);

        if (cancelled) return;
        setSkills(nextSkills);
        setBacktests(nextBacktests);
        setSignals(nextSignals);
        setLiveTasks(nextLiveTasks);
        setOverview(nextOverview);
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

  const signalFeed = useMemo(() => buildSignalFeed(signals, liveTasks, skills), [liveTasks, signals, skills]);
  const strategyInsights = useMemo(
    () => buildStrategyInsights(skills, liveTasks, signals, backtests),
    [backtests, liveTasks, signals, skills],
  );

  const featuredRun = backtests[0] ?? null;
  const featuredSignal = signalFeed[0] ?? null;
  const featuredStrategy = strategyInsights[0] ?? null;

  const stats = useMemo(
    () => [
      {
        label: 'Replay Runs',
        value: formatCount(backtests.length),
        detail: featuredRun ? `Latest run ${featuredRun.id}` : '等待第一次回放',
      },
      {
        label: 'Strategies',
        value: formatCount(skills.length),
        detail: `${formatCount(skills.filter((skill) => skill.validation_status === 'passed').length)} 个验证通过`,
      },
      {
        label: 'Today Signals',
        value: formatCount(countSignalsToday(signals)),
        detail: featuredSignal ? `Latest at ${formatTime(featuredSignal.signal.trigger_time_ms)}` : '暂无实时信号',
      },
      {
        label: 'Active Live Tasks',
        value: formatCount(liveTasks.filter((task) => task.status === 'active' || task.status === 'running').length),
        detail: liveTasks.length ? '产品侧已感知到实时执行链路' : '等待首个 live task 进入主界面',
      },
    ],
    [backtests.length, featuredRun, featuredSignal, liveTasks, signals, skills],
  );

  return (
    <div className="product-page-stack">
      <section className="hero-stage">
        <div className="hero-copy-panel neon-panel">
          <p className="section-kicker">Direct Product Experience</p>
          <h1>把 Agent 的交易判断，变成一场可直接进入的雨夜产品。</h1>
          <p className="hero-description">
            TradeSkills 现在先把你带进产品现场：先读策略、再看实时信号、最后进入多标的回放剧场。Console 仍保留，但它退回了旁页，专门服务调试与操作。
          </p>
          <div className="hero-actions">
            <Link className="neon-button neon-button-primary" to={featuredRun ? `/replays/${featuredRun.id}` : '/replays'}>
              {featuredRun ? '进入最新回放' : '进入 Replay Theater'}
            </Link>
            <Link className="neon-button neon-button-secondary" to="/signals">
              打开 Signals Deck
            </Link>
          </div>
        </div>

        <div className="hero-side-panel neon-panel neon-panel-accent">
          <p className="section-kicker">System Pulse</p>
          <div className="signal-spotlight">
            <span className="signal-dot" />
            <div>
              <strong>{featuredRun ? '最新回放已就绪' : loading ? '正在扫描产品上下文' : '等待第一条回放样本'}</strong>
              <p>
                {featuredRun
                  ? `${describeStatus(featuredRun.status)} / ${formatTime(featuredRun.updated_at_ms)}`
                  : '等第一条 backtest run 进入后，这里会把用户直接送进产品化回放页面。'}
              </p>
            </div>
          </div>
          {featuredSignal ? (
            <div className="mini-signal-card">
              <small>Latest Signal</small>
              <strong>{featuredSignal.signal.signal.symbol ?? '未指定标的'}</strong>
              <p>
                {describeAction(featuredSignal.signal.signal.action)} / {describeDirection(featuredSignal.signal.signal.direction)}
              </p>
            </div>
          ) : (
            <div className="mini-signal-card is-muted">
              <small>Latest Signal</small>
              <strong>暂无实时动作</strong>
              <p>等下一条 live signal 进入后，这里会展示方向、时间和对应策略。</p>
            </div>
          )}
          {featuredStrategy ? (
            <div className="mini-signal-card">
              <small>Featured Strategy</small>
              <strong>{featuredStrategy.skill.title}</strong>
              <p>
                {getSkillCadence(featuredStrategy.skill)} / {featuredStrategy.recentSymbols.slice(0, 2).join(' / ') || '等待 symbol 上下文'}
              </p>
            </div>
          ) : null}
          <Link className="inline-link" to="/console">
            Console 仍保留为旁页调试入口
          </Link>
        </div>
      </section>

      <section className="stats-grid">
        {stats.map((stat) => (
          <ProductStatTile key={stat.label} detail={stat.detail} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="neon-banner neon-banner-error">数据加载失败：{error}</div> : null}

      <section className="destination-grid">
        <Link className="destination-card" to={featuredRun ? `/replays/${featuredRun.id}` : '/replays'}>
          <small>Replay Theater</small>
          <strong>{featuredRun ? featuredRun.id : '先进入回放剧场'}</strong>
          <p>{featuredRun ? readTotalReturnText(featuredRun) : '从最新一次 run 进入多标的 Agent 交易叙事。'}</p>
          <div className="tag-row">
            <span className="meta-chip">{featuredRun ? describeStatus(featuredRun.status) : '等待样本'}</span>
            <span className="meta-chip">{featuredRun ? formatTime(featuredRun.updated_at_ms) : '由历史回放驱动'}</span>
          </div>
        </Link>

        <Link className="destination-card" to="/signals">
          <small>Signals Deck</small>
          <strong>实时信号与策略关系</strong>
          <p>把最新 live signal 组织成带策略上下文的前台 feed，而不只是后台输出记录。</p>
          <div className="tag-row">
            <span className="meta-chip">今日 {formatCount(countSignalsToday(signals))} 条</span>
            <span className="meta-chip">{formatCount(liveTasks.length)} 个任务上下文</span>
          </div>
        </Link>

        <Link className="destination-card" to={featuredStrategy ? `/strategies/${featuredStrategy.skill.id}` : '/strategies'}>
          <small>Strategy Profiles</small>
          <strong>{featuredStrategy ? featuredStrategy.skill.title : '读懂每条策略在怎么交易'}</strong>
          <p>{featuredStrategy ? getStrategyExcerpt(featuredStrategy.skill) : '把 cadence、risk、tooling 和最近执行状态整理成用户可读档案。'}</p>
          <div className="tag-row">
            <span className="meta-chip">{formatCount(skills.length)} 条策略</span>
            <span className="meta-chip">{overview ? `${formatCount(overview.total_symbols)} 个市场标的` : '市场概况载入中'}</span>
          </div>
        </Link>
      </section>

      <section className="content-grid two-column">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Featured Replays</p>
              <h2>从最新回放，直接进入产品现场</h2>
            </div>
            <Link className="inline-link" to="/replays">
              查看全部
            </Link>
          </div>
          <div className="story-list">
            {backtests.length ? (
              backtests.slice(0, 4).map((run) => (
                <Link className="story-card" key={run.id} to={`/replays/${run.id}`}>
                  <div>
                    <small>{describeStatus(run.status)}</small>
                    <strong>{run.id}</strong>
                  </div>
                  <p>{readTotalReturnText(run)}</p>
                  <span>{formatTime(run.created_at_ms)}</span>
                </Link>
              ))
            ) : (
              <div className="empty-product-card">
                <strong>还没有回放样本</strong>
                <p>先去 Console 创建一条 backtest，再回到这里体验回放剧场。</p>
              </div>
            )}
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Live Pulse</p>
              <h2>最近的实时信号</h2>
            </div>
            <Link className="inline-link" to="/signals">
              打开完整 feed
            </Link>
          </div>
          <div className="story-list">
            {signalFeed.length ? (
              signalFeed.slice(0, 4).map((item) => (
                <article className="story-card static-card signal-feed-card" key={item.signal.id}>
                  <div>
                    <small>{describeStatus(item.signal.delivery_status)}</small>
                    <strong>{item.signal.signal.symbol ?? '未指定标的'}</strong>
                  </div>
                  <p>
                    {describeAction(item.signal.signal.action)} / {describeDirection(item.signal.signal.direction)}
                  </p>
                  <span>{formatTime(item.signal.trigger_time_ms)}</span>
                  <div className="signal-card-footer">
                    {item.skill ? (
                      <Link className="inline-link" to={`/strategies/${item.skill.id}`}>
                        {item.skill.title}
                      </Link>
                    ) : (
                      <span className="muted-label">暂未解析到策略档案</span>
                    )}
                  </div>
                </article>
              ))
            ) : (
              <div className="empty-product-card">
                <strong>信号面板待激活</strong>
                <p>Console 里的 live task 仍然保留，激活后这里会变成产品化展示入口。</p>
              </div>
            )}
          </div>
        </article>
      </section>

      <section className="content-grid two-column">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Strategy Radar</p>
              <h2>先读懂策略，再进入交易现场</h2>
            </div>
            <Link className="inline-link" to="/strategies">
              浏览全部档案
            </Link>
          </div>
          <div className="story-list">
            {strategyInsights.length ? (
              strategyInsights.slice(0, 4).map((insight) => (
                <Link className="story-card" key={insight.skill.id} to={`/strategies/${insight.skill.id}`}>
                  <div>
                    <small>{describeStatus(insight.skill.validation_status)}</small>
                    <strong>{insight.skill.title}</strong>
                  </div>
                  <p>{getSkillCadence(insight.skill)} / {formatCount(insight.signals.length)} 条 signal</p>
                  <span>{insight.recentSymbols.slice(0, 3).join(' / ') || '等待执行上下文'}</span>
                </Link>
              ))
            ) : (
              <div className="empty-product-card">
                <strong>策略档案还在形成中</strong>
                <p>创建 Skill 后，首页会在这里出现可进入的 profile 入口。</p>
              </div>
            )}
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Product Map</p>
              <h2>这套产品逻辑怎么走</h2>
            </div>
          </div>
          <div className="flow-list">
            <div className="flow-step">
              <small>01 / Strategy Profiles</small>
              <strong>先理解策略的节奏、工具和风险边界</strong>
              <p>从 `/strategies` 开始，用户先建立对策略行为边界的理解，再进入后面的执行流。</p>
            </div>
            <div className="flow-step">
              <small>02 / Signals Deck</small>
              <strong>再看它最近发出了什么动作</strong>
              <p>Signals 页负责把 live output 翻译成可读前线，并且连回对应策略档案。</p>
            </div>
            <div className="flow-step">
              <small>03 / Replay Theater</small>
              <strong>最后进入多标的回放剧场验证它</strong>
              <p>Replay 页把单次 run 切成多标的剧情，让用户真正看见 Agent 怎么做出交易。</p>
            </div>
          </div>
          <div className="tag-row">
            <Link className="inline-link" to="/strategies">
              策略档案
            </Link>
            <Link className="inline-link" to="/signals">
              信号前线
            </Link>
            <Link className="inline-link" to="/replays">
              回放剧场
            </Link>
            <Link className="inline-link" to="/console">
              Console 旁页
            </Link>
          </div>
        </article>
      </section>
    </div>
  );
}
