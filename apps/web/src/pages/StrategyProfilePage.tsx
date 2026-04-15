import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import ProductStatTile from '../components/ProductStatTile';
import { getSkill, listBacktests, listLiveTasks, listSignals } from '../api';
import {
  describeAction,
  describeDirection,
  describeExtractionMethod,
  describeStatus,
  describeTriggerMode,
  describeRuntimeMode,
  formatCount,
  formatPercent,
  formatTime,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildStrategyInsights, getSkillCadence, getStrategyExcerpt } from '../lib/product';
import type { BacktestRun, LiveSignal, LiveTask, Skill } from '../types';

function yesNo(value: boolean | undefined, truthy: string, falsy: string): string {
  if (typeof value !== 'boolean') return '未声明';
  return value ? truthy : falsy;
}

function readTotalReturnPct(run: BacktestRun | null): number | null {
  if (!run) return null;
  const value = run.summary?.total_return_pct;
  return typeof value === 'number' ? Number(value) : null;
}

export default function StrategyProfilePage() {
  const { skillId } = useParams<{ skillId: string }>();
  const [skill, setSkill] = useState<Skill | null>(null);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!skillId) return;
    const currentSkillId = skillId;
    let cancelled = false;

    async function load() {
      setLoading(true);
      try {
        const [nextSkill, nextLiveTasks, nextSignals, nextBacktests] = await Promise.all([
          getSkill(currentSkillId),
          listLiveTasks(),
          listSignals(),
          listBacktests(),
        ]);

        if (cancelled) return;
        setSkill(nextSkill);
        setLiveTasks(nextLiveTasks);
        setSignals(nextSignals);
        setBacktests(nextBacktests);
        setError(null);
      } catch (nextError) {
        if (!cancelled) {
          setSkill(null);
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
  }, [skillId]);

  const insight = useMemo(() => {
    if (!skill) return null;
    return buildStrategyInsights([skill], liveTasks, signals, backtests)[0] ?? null;
  }, [backtests, liveTasks, signals, skill]);

  const latestReturn = readTotalReturnPct(insight?.latestBacktest ?? null);
  const requiredTools = skill?.envelope.tool_contract?.required_tools ?? [];
  const optionalTools = skill?.envelope.tool_contract?.optional_tools ?? [];
  const runtimeModes = skill?.envelope.runtime_modes ?? [];
  const outputFields = skill?.envelope.output_contract?.required_fields ?? [];
  const risk = skill?.envelope.risk_contract;
  const runtimeProfile = skill?.envelope.runtime_profile;

  const stats = useMemo(() => {
    return [
      {
        label: 'Cadence',
        value: skill ? getSkillCadence(skill) : '--',
        detail: skill ? describeTriggerMode(skill.envelope.trigger?.trigger_on) : '等待策略详情',
      },
      {
        label: 'Live Signals',
        value: formatCount(insight?.signals.length),
        detail: insight?.latestSignal ? `最近触发 ${formatTime(insight.latestSignal.trigger_time_ms)}` : '还没有实时信号样本',
      },
      {
        label: 'Recent Symbols',
        value: formatCount(insight?.recentSymbols.length),
        detail: insight?.recentSymbols.length ? insight.recentSymbols.slice(0, 3).join(' / ') : '等待首个交易标的',
      },
      {
        label: 'Replay Context',
        value: insight?.latestBacktest ? insight.latestBacktest.id : '--',
        detail: latestReturn == null ? '等待首条回放' : `最近收益 ${formatPercent(latestReturn)}`,
      },
    ];
  }, [insight, latestReturn, skill]);

  if (!loading && !skill) {
    return (
      <div className="product-page-stack">
        {error ? <div className="neon-banner neon-banner-error">策略档案加载失败：{error}</div> : null}
        <div className="empty-product-card wide-empty-card">
          <strong>没有找到这条策略</strong>
          <p>可能是策略已被删除，或当前环境还没有同步到这个 skill id。</p>
          <Link className="neon-button neon-button-secondary" to="/strategies">
            返回策略目录
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="product-page-stack">
      <section className="page-header-card neon-panel neon-panel-accent profile-hero-panel">
        <div className="section-heading-row profile-heading-row">
          <div>
            <p className="section-kicker">Strategy Profile</p>
            <h1 className="page-title">{skill?.title ?? skillId ?? 'Strategy'}</h1>
            <p className="page-description">{skill ? getStrategyExcerpt(skill) : '正在读取策略资料卡...'}</p>
          </div>
          <div className="profile-hero-meta">
            <span className={`tone-pill is-${toneForStatus(skill?.validation_status)}`}>
              {skill ? describeStatus(skill.validation_status) : '加载中'}
            </span>
            <span className="meta-chip">节奏 {skill ? getSkillCadence(skill) : '--'}</span>
            <span className="meta-chip">更新于 {skill ? formatTime(skill.updated_at_ms) : '--'}</span>
          </div>
        </div>
        <div className="hero-actions">
          {insight?.latestBacktest ? (
            <Link className="neon-button neon-button-primary" to={`/replays/${insight.latestBacktest.id}`}>
              进入最近回放
            </Link>
          ) : (
            <Link className="neon-button neon-button-primary" to="/signals">
              先看实时信号
            </Link>
          )}
          <Link className="neon-button neon-button-secondary" to="/strategies">
            返回策略目录
          </Link>
        </div>
      </section>

      <section className="stats-grid">
        {stats.map((stat) => (
          <ProductStatTile key={stat.label} detail={stat.detail} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="neon-banner neon-banner-error">策略上下文存在部分加载失败：{error}</div> : null}

      <section className="content-grid two-column">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Cadence & Runtime</p>
              <h2>执行节奏</h2>
            </div>
          </div>
          <div className="detail-grid">
            <div className="detail-block">
              <small>Execution Cadence</small>
              <strong>{skill ? getSkillCadence(skill) : '--'}</strong>
              <p>决定这条策略多久会再次扫描和做出决策。</p>
            </div>
            <div className="detail-block">
              <small>Trigger Mode</small>
              <strong>{describeTriggerMode(skill?.envelope.trigger?.trigger_on)}</strong>
              <p>当前策略是按 K 线收盘触发，还是按时钟周期触发。</p>
            </div>
            <div className="detail-block">
              <small>Runtime Modes</small>
              <strong>
                {runtimeModes.length ? runtimeModes.map((mode) => describeRuntimeMode(mode)).join(' / ') : '未声明'}
              </strong>
              <p>决定它更偏回放实验、实时信号，还是同时支持两种执行路径。</p>
            </div>
            <div className="detail-block">
              <small>Timezone</small>
              <strong>{skill?.envelope.trigger?.timezone ?? '未声明'}</strong>
              <p>如未声明，则使用系统默认执行时区。</p>
            </div>
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Risk Envelope</p>
              <h2>风险边界</h2>
            </div>
          </div>
          <div className="detail-grid">
            <div className="detail-block">
              <small>Max Position</small>
              <strong>{formatPercent(risk?.max_position_pct)}</strong>
              <p>单次仓位上限，决定策略是否偏保守或激进。</p>
            </div>
            <div className="detail-block">
              <small>Daily Loss Cap</small>
              <strong>{formatPercent(risk?.max_daily_loss_pct)}</strong>
              <p>若策略声明了日损上限，这里直接给出产品可读展示。</p>
            </div>
            <div className="detail-block">
              <small>Concurrent Positions</small>
              <strong>{typeof risk?.max_concurrent_positions === 'number' ? risk.max_concurrent_positions : '未声明'}</strong>
              <p>帮助用户理解它会不会频繁同时管理多个标的。</p>
            </div>
            <div className="detail-block">
              <small>Protective Rules</small>
              <strong>{yesNo(risk?.requires_stop_loss, '要求止损', '不要求止损')}</strong>
              <p>{yesNo(risk?.allow_hedging, '允许对冲', '不允许对冲')} / 用于还原策略的风格边界。</p>
            </div>
          </div>
        </article>
      </section>

      <section className="content-grid two-column">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Tooling Contract</p>
              <h2>工具与输出协议</h2>
            </div>
          </div>
          <div className="stacked-section">
            <div>
              <small className="muted-label">Required Tools</small>
              <div className="tag-row">
                {requiredTools.length ? requiredTools.map((tool) => <span className="meta-chip" key={tool}>{tool}</span>) : <span className="meta-chip">未声明必需工具</span>}
              </div>
            </div>
            <div>
              <small className="muted-label">Optional Tools</small>
              <div className="tag-row">
                {optionalTools.length ? optionalTools.map((tool) => <span className="meta-chip" key={tool}>{tool}</span>) : <span className="meta-chip">未声明可选工具</span>}
              </div>
            </div>
            <div>
              <small className="muted-label">Output Contract</small>
              <div className="tag-row">
                {skill?.envelope.output_contract?.schema ? <span className="meta-chip">Schema {skill.envelope.output_contract.schema}</span> : null}
                {outputFields.length ? outputFields.map((field) => <span className="meta-chip" key={field}>{field}</span>) : <span className="meta-chip">未声明关键输出字段</span>}
              </div>
            </div>
            <div className="detail-grid compact-grid">
              <div className="detail-block compact-block">
                <small>Market Scan</small>
                <strong>{yesNo(runtimeProfile?.needs_market_scan, '需要', '不需要')}</strong>
                <p>这条策略是否默认依赖多标的市场扫描。</p>
              </div>
              <div className="detail-block compact-block">
                <small>Python Sandbox</small>
                <strong>{yesNo(runtimeProfile?.needs_python_sandbox, '需要', '不需要')}</strong>
                <p>这条策略是否依赖更重的运行沙箱能力。</p>
              </div>
            </div>
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Validation Narrative</p>
              <h2>验证与抽取说明</h2>
            </div>
          </div>
          <div className="detail-grid compact-grid">
            <div className="detail-block compact-block">
              <small>Validation</small>
              <strong>{skill ? describeStatus(skill.validation_status) : '--'}</strong>
              <p>产品页优先展示已验证版本，降低阅读与体验成本。</p>
            </div>
            <div className="detail-block compact-block">
              <small>Extraction</small>
              <strong>{skill ? describeExtractionMethod(skill.extraction_method) : '--'}</strong>
              <p>{skill?.fallback_used ? '当前版本包含 LLM fallback。' : '当前版本主要通过规则提取。'}</p>
            </div>
          </div>

          <div className="stacked-section">
            <div className="story-card static-card compact-card">
              <small>Extraction Summary</small>
              <strong>{skill?.envelope.extraction_meta?.reasoning_summary ?? '当前版本没有额外抽取摘要。'}</strong>
            </div>
            {skill?.validation_warnings.length ? (
              <div className="story-card static-card compact-card">
                <small>Warnings</small>
                <strong>{skill.validation_warnings.join('；')}</strong>
              </div>
            ) : null}
            {skill?.validation_errors.length ? (
              <div className="story-card static-card compact-card">
                <small>Errors</small>
                <strong>{skill.validation_errors.join('；')}</strong>
              </div>
            ) : null}
          </div>
        </article>
      </section>

      <section className="content-grid two-column">
        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Live Context</p>
              <h2>最近的实时执行</h2>
            </div>
            <Link className="inline-link" to="/signals">
              去看 Signals
            </Link>
          </div>
          <div className="stacked-section">
            {insight?.liveTasks.length ? (
              insight.liveTasks.slice(0, 3).map((task) => (
                <div className="story-card static-card compact-card" key={task.id}>
                  <small>{describeStatus(task.status)}</small>
                  <strong>{task.id}</strong>
                  <p>节奏 {task.cadence} / 上次触发 {formatTime(task.last_triggered_at_ms)}</p>
                </div>
              ))
            ) : (
              <div className="empty-product-card wide-empty-card compact-empty-card">
                <strong>还没有 live task</strong>
                <p>这条策略还没有进入实时任务链路，所以暂时没有 execution cadence 的现场样本。</p>
              </div>
            )}

            {insight?.signals.length ? (
              insight.signals.slice(0, 3).map((signal) => (
                <div className="story-card static-card compact-card" key={signal.id}>
                  <small>{formatTime(signal.trigger_time_ms)}</small>
                  <strong>{signal.signal.symbol ?? '未指定标的'}</strong>
                  <p>
                    {describeAction(signal.signal.action)} / {describeDirection(signal.signal.direction)}
                  </p>
                </div>
              ))
            ) : null}
          </div>
        </article>

        <article className="neon-panel feature-panel">
          <div className="section-heading-row">
            <div>
              <p className="section-kicker">Replay Context</p>
              <h2>最近的回放证据</h2>
            </div>
            <Link className="inline-link" to="/replays">
              回放总览
            </Link>
          </div>
          <div className="stacked-section">
            {insight?.backtests.length ? (
              insight.backtests.slice(0, 4).map((run) => {
                const totalReturn = readTotalReturnPct(run);
                return (
                  <Link className="story-card compact-card" key={run.id} to={`/replays/${run.id}`}>
                    <small>{describeStatus(run.status)}</small>
                    <strong>{run.id}</strong>
                    <p>{totalReturn == null ? '等待汇总结果' : `总收益 ${formatPercent(totalReturn)}`}</p>
                    <span>{formatTime(run.updated_at_ms)}</span>
                  </Link>
                );
              })
            ) : (
              <div className="empty-product-card wide-empty-card compact-empty-card">
                <strong>还没有回放样本</strong>
                <p>这条策略一旦沉淀出 backtest run，这里就会出现可直接进入的 replay 证据链。</p>
              </div>
            )}
          </div>
        </article>
      </section>
    </div>
  );
}
