import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import PageHeader from '../components/PageHeader';
import ProductStatTile from '../components/ProductStatTile';
import LoadingSkeleton from '../components/LoadingSkeleton';
import { getLiveTaskPortfolio, getSkill, listBacktests, listLiveTasks, listSignals } from '../api';
import {
  describeStatus,
  describeTriggerMode,
  formatCount,
  formatPercent,
  formatSignedCurrency,
  formatSignedPercent,
  formatTime,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { buildStrategyInsights, getRunReturnPct, getSkillCadence, getStrategyExcerpt } from '../lib/product';
import type { BacktestRun, LiveSignal, LiveTask, PortfolioState, Skill } from '../types';

function yesNo(value: boolean | undefined, truthy: string, falsy: string): string {
  if (typeof value !== 'boolean') return '未声明';
  return value ? truthy : falsy;
}

export default function StrategyProfilePage() {
  const { skillId } = useParams<{ skillId: string }>();
  const [skill, setSkill] = useState<Skill | null>(null);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [portfoliosByTaskId, setPortfoliosByTaskId] = useState<Record<string, PortfolioState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!skillId) return;

    try {
      const [nextSkill, nextLiveTasks, nextSignals, nextBacktests] = await Promise.all([
        getSkill(skillId),
        listLiveTasks(),
        listSignals(),
        listBacktests(),
      ]);

      const linkedTask = nextLiveTasks.find((task) => task.skill_id === skillId && (task.status === 'active' || task.status === 'paused')) ?? null;
      const portfolios = linkedTask ? { [linkedTask.id]: await getLiveTaskPortfolio(linkedTask.id) } : {};

      setSkill(nextSkill);
      setLiveTasks(nextLiveTasks);
      setSignals(nextSignals);
      setBacktests(nextBacktests);
      setPortfoliosByTaskId(portfolios);
      setError(null);
    } catch (nextError) {
      setSkill(null);
      setError(getErrorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }, [skillId]);

  useEffect(() => {
    void load();
  }, [load]);

  const insight = useMemo(() => {
    if (!skill) return null;
    return buildStrategyInsights([skill], liveTasks, signals, backtests, portfoliosByTaskId)[0] ?? null;
  }, [backtests, liveTasks, portfoliosByTaskId, signals, skill]);

  const risk = skill?.envelope.risk_contract;
  const toolContract = skill?.envelope.tool_contract;
  const extractionMeta = skill?.envelope.extraction_meta;
  const latestReturn = getRunReturnPct(insight?.latestBacktest ?? null);

  const stats = [
    {
      label: '执行节奏',
      value: skill ? getSkillCadence(skill) : '--',
      detail: skill ? describeTriggerMode(skill.envelope.trigger?.trigger_on) : '读取中',
    },
    {
      label: '实时上下文',
      value: insight?.liveTask ? describeStatus(insight.liveTask.status) : '未启动',
      detail: insight?.liveTask ? `最后活动 ${formatTime(insight.liveTask.last_activity_at_ms ?? insight.liveTask.last_triggered_at_ms)}` : '暂无实时运行',
    },
    {
      label: '最近回测',
      value: insight?.latestBacktest?.id ?? '--',
      detail: latestReturn == null ? '等待首条回测' : `收益 ${formatSignedPercent(latestReturn)}`,
    },
    {
      label: '最近信号',
      value: formatCount(insight?.signals.length ?? 0),
      detail: insight?.latestSignal ? formatTime(insight.latestSignal.trigger_time_ms) : '暂无实时信号',
    },
  ];

  const contractRows = [
    {
      term: '触发节奏',
      value: skill ? getSkillCadence(skill) : '--',
      detail: skill ? describeTriggerMode(skill.envelope.trigger?.trigger_on) : '读取中',
      sideLabel: '执行上下文',
      sideValue: '历史回放 / 实时触发',
      sideDetail: '同一份策略定义同时适用于回放和实时执行；修改请创建新版本。',
    },
    {
      term: '风险约束',
      value: formatPercent(risk?.max_position_pct),
      detail: `日损上限 ${formatPercent(risk?.max_daily_loss_pct)} / 最多 ${risk?.max_concurrent_positions ?? '--'} 个持仓`,
      sideLabel: '保护规则',
      sideValue: yesNo(risk?.requires_stop_loss, '要求止损', '未声明止损'),
      sideDetail: yesNo(risk?.allow_hedging, '允许对冲', '默认不对冲'),
    },
    {
      term: '必需工具',
      value: toolContract?.required_tools?.length ? toolContract.required_tools.join(', ') : '未声明',
      detail: '判断执行时所依赖的能力边界。',
      sideLabel: '可选工具',
      sideValue: toolContract?.optional_tools?.length ? toolContract.optional_tools.join(', ') : '未声明',
      sideDetail: '未声明时无额外可选工具约束。',
    },
    {
      term: '提取方式',
      value: skill?.extraction_method === 'llm_fallback' ? 'LLM 回退' : '规则提取',
      detail: extractionMeta?.reasoning_summary ?? '无额外抽取摘要。',
      sideLabel: '校验警告',
      sideValue: skill?.validation_warnings.length ? skill.validation_warnings.join('；') : '无',
      sideDetail: '策略带着这些说明进入执行流程。',
    },
  ];

  const executionRows = [
    {
      term: '实时运行',
      value: insight?.liveTask ? describeStatus(insight.liveTask.status) : '未启动',
      detail: insight?.liveTask
        ? `收益 ${formatSignedPercent(insight.livePortfolio?.account?.total_return_pct)} / 权益 ${formatSignedCurrency(
            insight.livePortfolio?.account?.equity,
          )}`
        : '当前没有活跃实时运行。',
      sideLabel: '最近信号',
      sideValue: insight?.latestSignal?.signal.symbol ?? '暂无',
      sideDetail: insight?.latestSignal ? formatTime(insight.latestSignal.trigger_time_ms) : '等待实时信号',
    },
    {
      term: '最近回测',
      value: insight?.latestBacktest?.id ?? '暂无',
      detail: latestReturn == null ? '等待首条回测' : `收益 ${formatSignedPercent(latestReturn)}`,
      sideLabel: '最近标的',
      sideValue: insight?.recentSymbols.length ? insight.recentSymbols.join(' / ') : '暂无',
      sideDetail: '策略当前覆盖的市场。',
    },
  ];

  if (!loading && !skill) {
    return (
      <div className="page-stack">
        {error ? <div className="feedback-banner is-error">{error}</div> : null}
        <section className="surface">
          <div className="empty-state">
            <strong>没有找到这条策略</strong>
            <p>它可能已经被删除，或当前环境还未同步到这个策略版本。</p>
            <Link className="action-button" to="/strategies">
              返回策略页
            </Link>
          </div>
        </section>
      </div>
    );
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="策略档案"
        title={skill?.title ?? skillId ?? '策略详情'}
        description={skill ? getStrategyExcerpt(skill) : '正在读取...'}
        backTo="/strategies"
        backLabel="策略列表"
        status={
          <>
            <span className={`status-pill is-${toneForStatus(skill?.validation_status)}`}>{describeStatus(skill?.validation_status)}</span>
            <span className="info-pill">不可变版本</span>
          </>
        }
      />

      {loading ? (
        <LoadingSkeleton variant="stat" />
      ) : (
        <section className="metric-grid">
          {stats.map((stat) => (
            <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
          ))}
        </section>
      )}

      {error ? <div className="feedback-banner is-error">{error}</div> : null}

      <section className="dual-grid">
        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">策略定义</p>
              <h2>合约详情</h2>
            </div>
          </div>
          <div className="spec-sheet">
            {contractRows.map((row, index) => (
              <article className={`spec-row${index === 0 ? ' is-emphasis' : ''}`} key={row.term}>
                <div className="spec-term-block">
                  <span className="spec-term">{row.term}</span>
                </div>
                <div className="spec-main">
                  <strong>{row.value}</strong>
                  <p>{row.detail}</p>
                </div>
                <div className="spec-side">
                  <span className="spec-side-label">{row.sideLabel}</span>
                  <strong>{row.sideValue}</strong>
                  <p>{row.sideDetail}</p>
                </div>
              </article>
            ))}
          </div>
        </section>

        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">关联执行</p>
              <h2>执行概览</h2>
            </div>
          </div>
          <div className="spec-sheet">
            {executionRows.map((row, index) => (
              <article className={`spec-row${index === 0 ? ' is-emphasis' : ''}`} key={row.term}>
                <div className="spec-term-block">
                  <span className="spec-term">{row.term}</span>
                </div>
                <div className="spec-main">
                  <strong>{row.value}</strong>
                  <p>{row.detail}</p>
                </div>
                <div className="spec-side">
                  <span className="spec-side-label">{row.sideLabel}</span>
                  <strong>{row.sideValue}</strong>
                  <p>{row.sideDetail}</p>
                </div>
              </article>
            ))}
          </div>

          <div className="action-cluster" style={{ marginTop: 16 }}>
            {insight?.latestBacktest ? (
              <Link className="action-button" to={`/replays/${insight.latestBacktest.id}`}>
                打开最近回测
              </Link>
            ) : null}
            {skill ? (
              <Link className="action-button" to="/signals">
                查看实时监控
              </Link>
            ) : null}
          </div>
        </section>
      </section>

      {skill?.raw_text ? (
        <section className="surface">
          <div className="section-head">
            <div>
              <p className="section-eyebrow">原始文本</p>
              <h2>策略原文</h2>
            </div>
          </div>
          <pre style={{ whiteSpace: 'pre-wrap', wordBreak: 'break-word', margin: 0, padding: 16, fontSize: 14, lineHeight: 1.6 }}>
            {skill.raw_text}
          </pre>
        </section>
      ) : null}
    </div>
  );
}
