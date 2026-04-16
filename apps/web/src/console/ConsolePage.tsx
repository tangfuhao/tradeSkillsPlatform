import { FormEvent, ReactNode, useEffect, useMemo, useState } from 'react';
import {
  DEFAULT_BACKTEST_INITIAL_CAPITAL,
  getDefaultBacktestWindow,
  resolveBacktestLaunchRequest,
} from '../lib/backtest';
import { formatPreciseTime, formatShortDuration } from '../lib/formatting';
import {
  createBacktest,
  createLiveTask,
  createSkill,
  getAgentRunnerBaseUrl,
  getAgentRunnerHealth,
  getApiBaseUrl,
  getApiHealth,
  getMarketOverview,
  listBacktestTraces,
  listBacktests,
  listLiveTasks,
  listSignals,
  listSkills,
  triggerLiveTask,
} from '../api';
import type {
  ApiHealthResponse,
  BacktestRun,
  BacktestTrace,
  LiveSignal,
  LiveTask,
  MarketOverview,
  ServicePulse,
  Skill,
  ToolCall,
} from '../types';

import './console.css';

const LOCALE = 'zh-CN';

const defaultSkill = `# 短线过热做空策略

## 执行节奏
每 15 分钟执行一次。

## 步骤 1 - 扫描市场
扫描 OKX 的 USDT 永续合约，优先关注短时间快速拉升、成交活跃、情绪拥挤的币种。

## 步骤 2 - 收集数据
拉取候选标的 15 分钟和 4 小时 K 线，计算 EMA20、EMA60、RSI14 与 ATR14。
若接口可用，再补充资金费率与持仓量变化。

## 步骤 3 - AI 推理
你是一名 AI 交易员，请判断哪一个山寨币最像短线过热后的做空机会。
如果结构不清晰，直接跳过本轮。

## 步骤 4 - 输出信号
仅当置信度足够高时才开仓做空，单次仓位不超过账户权益的 10%。

## 风险控制
- 每笔仓位必须带 2% 的止损。
- 初始止盈目标为 10%。
- 单日最大回撤不超过 8%。
- 同时持仓不超过 2 个。
- 不允许对冲。`;

const generalStatusLabels: Record<string, string> = {
  ok: '正常',
  healthy: '正常',
  queued: '排队中',
  running: '运行中',
  completed: '已完成',
  succeeded: '同步成功',
  no_advance: '无新增进度',
  blocked: '已阻塞',
  disabled: '已关闭',
  failed: '失败',
  active: '已激活',
  stored: '已存储',
  pending: '待处理',
  passed: '已通过',
  validation_failed: '验证失败',
  degraded: '降级',
  skipped: '已跳过',
  not_available: '暂不可用',
};

const syncBlockReasonLabels: Record<string, string> = {
  no_active_universe: '交易所活跃合约列表为空',
  tier1_incomplete: '核心 Tier1 标的覆盖不完整',
  coverage_below_threshold: '整体覆盖率低于派发阈值',
};

const actionLabels: Record<string, string> = {
  skip: '跳过',
  watch: '观察',
  open_position: '开仓',
  close_position: '平仓',
  reduce_position: '减仓',
  hold: '持有',
};

const directionLabels: Record<string, string> = {
  long: '做多',
  short: '做空',
  buy: '做多',
  sell: '做空',
};

const scopeLabels: Record<string, string> = {
  historical: '历史回放',
};

const llmRoundResultLabels: Record<string, string> = {
  tool_calls: '触发工具调用',
  final_output: '返回最终结果',
};

function translateToken(value?: string | null, dictionary: Record<string, string> = {}): string {
  if (!value) return '--';
  return dictionary[value] ?? value.replace(/_/g, ' ');
}

function describeExtractionMethod(value?: Skill['extraction_method']): string {
  if (value === 'llm_fallback') return 'LLM 回退';
  return '规则提取';
}

function formatTime(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--';
  return new Intl.DateTimeFormat(LOCALE, {
    dateStyle: 'medium',
    timeStyle: 'short',
    hour12: false,
  }).format(date);
}

function formatCount(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return new Intl.NumberFormat(LOCALE).format(value);
}

function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

function formatDuration(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value) || value < 0) return '--';
  return formatShortDuration(value);
}

function describeStatus(status?: string | null): string {
  return translateToken(status, generalStatusLabels);
}

function describeSyncBlockReason(reason?: string | null): string {
  return translateToken(reason, syncBlockReasonLabels);
}

function describeAction(action?: string | null): string {
  return translateToken(action, actionLabels);
}

function describeDirection(direction?: string | null): string {
  return translateToken(direction, directionLabels);
}

function describeScope(scope?: string | null): string {
  return translateToken(scope, scopeLabels);
}

function describeLlmRoundResult(resultType?: string | null): string {
  return translateToken(resultType, llmRoundResultLabels);
}

function summarizeDecision(decision: Record<string, unknown>): string {
  const action = describeAction(typeof decision.action === 'string' ? decision.action : 'skip');
  const symbol = typeof decision.symbol === 'string' ? decision.symbol : null;
  const direction = describeDirection(typeof decision.direction === 'string' ? decision.direction : null);
  const sizePct = typeof decision.size_pct === 'number' ? formatPercent(decision.size_pct) : null;
  return [action, symbol, direction === '--' ? null : direction, sizePct].filter(Boolean).join(' / ');
}

function summarizeToolSequence(toolCalls: ToolCall[]): string {
  if (!toolCalls.length) return '暂无工具调用';
  return toolCalls.map((call) => call.tool_name).join(' -> ');
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2) ?? 'null';
}

function isBacktestActive(status?: string): boolean {
  return status === 'queued' || status === 'running';
}

function countSignalsToday(signals: LiveSignal[]): number {
  const today = new Intl.DateTimeFormat(LOCALE, { dateStyle: 'short' }).format(new Date());
  return signals.filter((signal) => {
    const signalDate = new Date(signal.trigger_time_ms);
    if (Number.isNaN(signalDate.getTime())) return false;
    return new Intl.DateTimeFormat(LOCALE, { dateStyle: 'short' }).format(signalDate) === today;
  }).length;
}

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}

function toneForStatus(status?: string | null): 'ok' | 'warn' | 'error' | 'neutral' {
  if (!status) return 'neutral';
  if (['ok', 'healthy', 'completed', 'active', 'stored', 'passed', 'succeeded'].includes(status)) {
    return 'ok';
  }
  if (['queued', 'running', 'pending', 'skipped', 'no_advance'].includes(status)) {
    return 'warn';
  }
  if (['failed', 'validation_failed', 'degraded', 'blocked'].includes(status)) {
    return 'error';
  }
  return 'neutral';
}

type PanelHeaderProps = {
  title: string;
  subtitle?: string;
  action?: ReactNode;
};

function PanelHeader({ title, subtitle, action }: PanelHeaderProps) {
  return (
    <div className="section-head console-section-head">
      <div>
        <p className="section-eyebrow">Operator Console</p>
        <h2>{title}</h2>
        {subtitle ? <p className="section-note">{subtitle}</p> : null}
      </div>
      {action ?? null}
    </div>
  );
}

type MetricCardProps = {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: 'accent' | 'warm' | 'neutral';
};

function MetricCard({ label, value, detail, tone = 'neutral' }: MetricCardProps) {
  return (
    <div className={`metric-tile console-metric-tile tone-${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <p>{detail}</p> : null}
    </div>
  );
}

type ListCardProps = {
  active?: boolean;
  interactive?: boolean;
  title: ReactNode;
  subtitle: ReactNode;
  meta?: ReactNode;
  badge?: ReactNode;
  onClick?: () => void;
};

function ListCard({ active = false, interactive = true, title, subtitle, meta, badge, onClick }: ListCardProps) {
  const className = `list-card ${active ? 'selected-card' : ''} ${interactive ? '' : 'static'}`.trim();
  const content = (
    <>
      <div className="list-card-top">
        <strong>{title}</strong>
        {badge ? <span className="mini-badge">{badge}</span> : null}
      </div>
      <span>{subtitle}</span>
      {meta ? <small>{meta}</small> : null}
    </>
  );

  if (!interactive) {
    return <div className={className}>{content}</div>;
  }

  return (
    <button className={className} type="button" onClick={onClick}>
      {content}
    </button>
  );
}

export default function ConsolePage() {
  const [skillText, setSkillText] = useState(defaultSkill);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [servicePulse, setServicePulse] = useState<ServicePulse[]>([]);
  const [apiHealth, setApiHealth] = useState<ApiHealthResponse | null>(null);
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedBacktestId, setSelectedBacktestId] = useState('');
  const [backtestTraces, setBacktestTraces] = useState<BacktestTrace[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [message, setMessage] = useState('准备就绪，可以开始编排新的策略。');
  const [loading, setLoading] = useState(false);
  const [backtestStart, setBacktestStart] = useState('');
  const [backtestEnd, setBacktestEnd] = useState('');
  const [backtestWindowInitialized, setBacktestWindowInitialized] = useState(false);
  const [initialCapital, setInitialCapital] = useState(DEFAULT_BACKTEST_INITIAL_CAPITAL);

  const selectedSkill = useMemo(
    () => skills.find((skill) => skill.id === selectedSkillId) ?? skills[0],
    [skills, selectedSkillId],
  );
  const selectedTask = useMemo(
    () => liveTasks.find((task) => task.id === selectedTaskId) ?? liveTasks[0],
    [liveTasks, selectedTaskId],
  );
  const selectedBacktest = useMemo(
    () => backtests.find((run) => run.id === selectedBacktestId) ?? backtests[0],
    [backtests, selectedBacktestId],
  );

  const latestCsvJob = marketOverview?.recent_csv_jobs?.[0] ?? null;
  const skippedSyncCount = marketOverview?.sync_cursors.filter((cursor) => cursor.status === 'skipped').length ?? 0;
  const failedSyncCount = marketOverview?.sync_cursors.filter((cursor) => cursor.status === 'failed').length ?? 0;
  const traceAutoRefresh = isBacktestActive(selectedBacktest?.status);
  const hasHistoricalCoverage = marketOverview?.coverage_start_ms != null && marketOverview?.coverage_end_ms != null;

  const heroMetrics = useMemo(() => {
    const passedCount = skills.filter((skill) => skill.validation_status === 'passed').length;
    const activeBacktests = backtests.filter((run) => isBacktestActive(run.status)).length;
    const activeLiveTasks = liveTasks.filter((task) => task.status === 'active').length;
    const todaySignals = countSignalsToday(signals);

    return [
      {
        label: '策略版本',
        value: formatCount(skills.length),
        detail: `${formatCount(passedCount)} 个验证通过`,
        tone: 'accent' as const,
      },
      {
        label: '回放队列',
        value: formatCount(activeBacktests),
        detail: backtests.length ? `${formatCount(backtests.length)} 条回放记录` : '等待第一次回放',
        tone: 'neutral' as const,
      },
      {
        label: '实时任务',
        value: formatCount(activeLiveTasks),
        detail: activeLiveTasks ? '等待同步行情驱动执行' : '尚未激活实时任务',
        tone: 'warm' as const,
      },
      {
        label: '今日信号',
        value: formatCount(todaySignals),
        detail: signals.length ? `${formatCount(signals.length)} 条累计输出` : '暂无信号存档',
        tone: 'neutral' as const,
      },
    ];
  }, [backtests, liveTasks, signals, skills]);

  const liveOpsSummary = useMemo(() => {
    const activeTaskCount = liveTasks.filter((task) => task.status === 'active').length;
    const latestCompletedSlotMs = liveTasks.reduce<number | null>(
      (latest, task) => {
        if (typeof task.last_completed_slot_as_of_ms !== 'number') return latest;
        return latest == null ? task.last_completed_slot_as_of_ms : Math.max(latest, task.last_completed_slot_as_of_ms);
      },
      null,
    );
    const latestTriggeredAtMs = liveTasks.reduce<number | null>(
      (latest, task) => {
        if (typeof task.last_triggered_at_ms !== 'number') return latest;
        return latest == null ? task.last_triggered_at_ms : Math.max(latest, task.last_triggered_at_ms);
      },
      null,
    );
    const latestSignalAtMs = signals.reduce<number | null>(
      (latest, signal) => (latest == null ? signal.trigger_time_ms : Math.max(latest, signal.trigger_time_ms)),
      null,
    );
    const idleTaskCount = liveTasks.filter((task) => task.status === 'active' && task.last_completed_slot_as_of_ms == null).length;

    return {
      activeTaskCount,
      todaySignals: countSignalsToday(signals),
      latestCompletedSlotMs,
      latestTriggeredAtMs,
      latestSignalAtMs,
      idleTaskCount,
    };
  }, [liveTasks, signals]);

  const exchangeSyncSummary = useMemo(() => {
    const sync = apiHealth?.market_sync;
    return {
      loopRunning: apiHealth?.market_sync_loop_running ?? false,
      lastStatus: apiHealth?.last_sync_status ?? null,
      lastStartedAtMs: apiHealth?.last_sync_started_at_ms ?? null,
      lastCompletedAtMs: apiHealth?.last_sync_completed_at_ms ?? null,
      lastError: apiHealth?.last_sync_error ?? null,
      coverageRatio: sync?.coverage_ratio ?? null,
      dispatchAsOfMs: sync?.dispatch_as_of_ms ?? null,
      snapshotAgeMs: sync?.snapshot_age_ms ?? null,
      universeActiveCount: sync?.universe_active_count ?? 0,
      freshSymbolCount: sync?.fresh_symbol_count ?? 0,
      missingSymbolCount: sync?.missing_symbol_count ?? 0,
      degraded: sync?.degraded ?? false,
      blockedReason: sync?.blocked_reason ?? null,
      bootstrapPendingCount: marketOverview?.bootstrap_pending_count ?? 0,
      backfillLagCount: marketOverview?.backfill_lag_symbol_count ?? 0,
    };
  }, [apiHealth, marketOverview]);

  const showSyncError = useMemo(() => {
    if (!exchangeSyncSummary.lastError) return false;
    if (exchangeSyncSummary.lastStatus === 'disabled') return false;
    return exchangeSyncSummary.lastStatus === 'failed' || Boolean(exchangeSyncSummary.blockedReason);
  }, [exchangeSyncSummary.blockedReason, exchangeSyncSummary.lastError, exchangeSyncSummary.lastStatus]);

  async function refreshDashboard() {
    const [apiHealth, runnerHealth, overview, nextSkills, nextBacktests, nextLiveTasks, nextSignals] = await Promise.all([
      getApiHealth(),
      getAgentRunnerHealth(),
      getMarketOverview(),
      listSkills(),
      listBacktests(),
      listLiveTasks(),
      listSignals(),
    ]);

    setServicePulse([
      { name: '后端 API', status: apiHealth.status, details: getApiBaseUrl() },
      { name: 'Agent Runner', status: runnerHealth.status, details: getAgentRunnerBaseUrl() },
    ]);
    setApiHealth(apiHealth);
    setMarketOverview(overview);
    setSkills(nextSkills);
    setBacktests(nextBacktests);
    setLiveTasks(nextLiveTasks);
    setSignals(nextSignals);

    if (nextSkills[0] && !nextSkills.some((skill) => skill.id === selectedSkillId)) {
      setSelectedSkillId(nextSkills[0].id);
    }
    if (nextLiveTasks[0] && !nextLiveTasks.some((task) => task.id === selectedTaskId)) {
      setSelectedTaskId(nextLiveTasks[0].id);
    }
    if (nextBacktests[0] && !nextBacktests.some((run) => run.id === selectedBacktestId)) {
      setSelectedBacktestId(nextBacktests[0].id);
    }
    if (!nextBacktests.length) {
      setSelectedBacktestId('');
    }
  }

  async function refreshTraceViewer(runId: string, silent = false) {
    if (!silent) {
      setTraceLoading(true);
    }

    try {
      const traces = await listBacktestTraces(runId);
      setBacktestTraces(traces);
      setTraceError(null);
    } catch (error) {
      setTraceError(`读取轨迹失败：${getErrorMessage(error)}`);
    } finally {
      if (!silent) {
        setTraceLoading(false);
      }
    }
  }

  useEffect(() => {
    refreshDashboard().catch((error) => {
      setMessage(`初始化检查失败：${getErrorMessage(error)}`);
    });
  }, []);

  useEffect(() => {
    if (backtestWindowInitialized) {
      return;
    }
    const nextWindow = getDefaultBacktestWindow(marketOverview);
    if (!nextWindow) {
      return;
    }
    setBacktestStart(nextWindow.start);
    setBacktestEnd(nextWindow.end);
    setBacktestWindowInitialized(true);
  }, [marketOverview, backtestWindowInitialized]);

  useEffect(() => {
    if (!selectedBacktest?.id) {
      setBacktestTraces([]);
      setTraceError(null);
      return;
    }

    refreshTraceViewer(selectedBacktest.id).catch((error) => {
      setTraceError(`读取轨迹失败：${getErrorMessage(error)}`);
    });
  }, [selectedBacktest?.id]);

  useEffect(() => {
    if (!selectedBacktest?.id || !traceAutoRefresh) {
      return undefined;
    }

    const timer = window.setInterval(() => {
      Promise.all([refreshDashboard(), refreshTraceViewer(selectedBacktest.id, true)]).catch((error) => {
        setTraceError(`刷新轨迹失败：${getErrorMessage(error)}`);
      });
    }, 2500);

    return () => window.clearInterval(timer);
  }, [selectedBacktest?.id, traceAutoRefresh]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextSkillText = skillText.trim();
    if (!nextSkillText) {
      setMessage('请先输入策略内容，再上传。');
      return;
    }

    setLoading(true);
    setMessage('正在上传策略并提取运行约束...');
    try {
      const created = await createSkill({ skill_text: nextSkillText });
      setSelectedSkillId(created.id);
      setMessage(
        created.fallback_used
          ? `策略《${created.title}》已生成；规则提取不足的部分已通过 LLM 回退补全，可直接用于历史回放和实时信号。`
          : `策略《${created.title}》已生成，可以直接用于历史回放和实时信号。`,
      );
      await refreshDashboard();
    } catch (error) {
      setMessage(`策略上传失败：${getErrorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleBacktest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSkill) {
      setMessage('请先创建或选择一个策略，再发起回放。');
      return;
    }
    if (!hasHistoricalCoverage) {
      setMessage('当前没有可用的本地历史数据，请先导入 CSV 后再发起回放。');
      return;
    }

    const nextRequest = resolveBacktestLaunchRequest({
      overview: marketOverview,
      startInput: backtestStart,
      endInput: backtestEnd,
      initialCapital,
      cadence: selectedSkill.envelope?.trigger?.value,
    });
    if (nextRequest.error) {
      setMessage(nextRequest.error);
      return;
    }
    const payload = nextRequest.payload;
    if (!payload) {
      setMessage('回放请求准备失败，请重新选择时间窗口。');
      return;
    }

    setLoading(true);
    setMessage('正在排队创建回放任务...');
    try {
      const created = await createBacktest({
        skill_id: selectedSkill.id,
        ...payload,
      });
      setSelectedBacktestId(created.id);
      setBacktestTraces([]);
      setTraceError(null);
      setMessage(`回放任务 ${created.id} 已进入队列，执行轨迹会自动刷新。`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`创建回放失败：${getErrorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleActivateLiveTask() {
    if (!selectedSkill) {
      setMessage('请先创建或选择一个策略，再开启实时任务。');
      return;
    }

    setLoading(true);
    setMessage('正在激活实时任务，后续会在真实行情同步到新 slot 后执行...');
    try {
      const created = await createLiveTask({ skill_id: selectedSkill.id });
      setSelectedTaskId(created.id);
      setMessage(`实时任务 ${created.id} 已激活，将在同步行情到达后按 ${created.cadence} slot 执行。`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`激活实时任务失败：${getErrorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleTriggerLiveTask() {
    if (!selectedTask) {
      setMessage('请先激活一个实时任务，再手动触发。');
      return;
    }

    setLoading(true);
    setMessage('正在立刻执行一次实时信号任务...');
    try {
      const signal = await triggerLiveTask(selectedTask.id);
      if (signal.delivery_status === 'failed') {
        setMessage(`实时任务 ${selectedTask.id} 执行失败：${signal.signal?.error_message ?? '请查看最近信号列表。'}`);
      } else {
        setMessage(`实时任务 ${selectedTask.id} 已产出新的信号记录。`);
      }
      await refreshDashboard();
    } catch (error) {
      setMessage(`手动触发失败：${getErrorMessage(error)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page-stack console-page">
      <section className="hero-panel surface console-hero">
        <div className="hero-copy-block">
          <p className="section-eyebrow">Operator Console</p>
          <h1>把策略编排、历史回放和实时信号统一收进一个中文版工作台。</h1>
          <p className="hero-copy">
            用自然语言撰写交易 Skill，系统会抽取运行约束、连接本地 OKX 历史数据，并把回放实验和实时任务放在同一条工作流里。
          </p>
          <div className="hero-tags">
            <span className="info-pill">中文界面</span>
            <span className="info-pill">回放优先</span>
            <span className="info-pill">统一风控</span>
            <span className="info-pill">实时信号</span>
          </div>
        </div>

        <div className="hero-side">
          <div className={`feedback-banner console-status-banner ${loading ? 'is-loading' : ''}`}>
            <div>
              <p className="section-eyebrow">{loading ? '系统忙碌中' : '系统提示'}</p>
              <strong>{loading ? '正在处理请求' : '控制台已就绪'}</strong>
              <p>{message}</p>
            </div>
          </div>

          <div className="hero-metrics">
            {heroMetrics.map((item) => (
              <MetricCard key={item.label} label={item.label} value={item.value} detail={item.detail} tone={item.tone} />
            ))}
          </div>
        </div>
      </section>

      <section className="dual-grid console-overview-grid">
        <article className="surface">
          <PanelHeader
            title="运行脉冲"
            subtitle="检查核心服务是否在线，以及当前连接的地址。"
            action={
              <button className="action-button" type="button" onClick={() => refreshDashboard().catch((error) => setMessage(`刷新失败：${getErrorMessage(error)}`))}>
                刷新数据
              </button>
            }
          />
          <div className="pulse-grid">
            {servicePulse.length ? (
              servicePulse.map((item) => (
                <div className={`pulse-card tone-${toneForStatus(item.status)}`} key={item.name}>
                  <div className="pulse-card-head">
                    <p>{item.name}</p>
                    <span className={`status-pill is-${toneForStatus(item.status)}`}>{describeStatus(item.status)}</span>
                  </div>
                  <strong>{item.details ?? '--'}</strong>
                  <span>状态回传正常后，这里会显示你当前使用的服务入口。</span>
                </div>
              ))
            ) : (
              <div className="empty-state">
                <p>正在拉取服务状态，请稍候。</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface">
          <PanelHeader title="市场数据面板" subtitle="本地历史覆盖、基础粒度与最近同步结果一目了然。" />
          <div className="insight-grid">
            <MetricCard label="覆盖币种" value={formatCount(marketOverview?.total_symbols)} detail="已纳入本地历史仓库的交易标的数量" tone="accent" />
            <MetricCard label="1 分钟 K 线" value={formatCount(marketOverview?.total_candles)} detail="供回放与聚合计算使用的基础数据量" />
            <MetricCard label="覆盖开始" value={formatTime(marketOverview?.coverage_start_ms)} detail="最早可用于回放的数据时间点" />
            <MetricCard label="覆盖结束" value={formatTime(marketOverview?.coverage_end_ms)} detail="最近一次落盘后的时间边界" tone="warm" />
          </div>
          <div className="meta-strip">
            <div className="info-box compact-box">
              <p>基础周期</p>
              <strong>{marketOverview?.base_timeframe ?? '--'}</strong>
            </div>
            <div className="info-box compact-box">
              <p>最近导入</p>
              <strong>{latestCsvJob ? `${formatCount(latestCsvJob.rows_inserted)} 行` : '--'}</strong>
            </div>
            <div className="info-box compact-box">
              <p>同步跳过</p>
              <strong>{formatCount(skippedSyncCount)}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="surface">
        <PanelHeader title="同步态势" subtitle="用最少的信息看清实时任务是否在跑、交易所同步是否推进，以及服务器有没有卡住。" />
        <div className="sync-status-grid">
          <article className="sync-status-card">
            <div className="sync-status-head">
              <div>
                <p className="section-eyebrow">Realtime</p>
                <h3>实时执行</h3>
              </div>
              <span className={`status-pill is-${liveOpsSummary.activeTaskCount ? 'ok' : 'warn'}`}>
                {liveOpsSummary.activeTaskCount ? '已接入' : '待激活'}
              </span>
            </div>
            <div className="sync-status-metrics">
              <MetricCard
                label="活跃任务"
                value={formatCount(liveOpsSummary.activeTaskCount)}
                detail={liveOpsSummary.idleTaskCount ? `${formatCount(liveOpsSummary.idleTaskCount)} 个尚未完成首个 slot` : '任务等待新行情 slot 驱动'}
                tone="accent"
              />
              <MetricCard
                label="最近完成 slot"
                value={formatTime(liveOpsSummary.latestCompletedSlotMs)}
                detail="这是服务器最近一次把实时任务推进到的新时间点"
                tone="neutral"
              />
              <MetricCard
                label="今日信号"
                value={formatCount(liveOpsSummary.todaySignals)}
                detail={`最近信号 ${formatTime(liveOpsSummary.latestSignalAtMs)}`}
                tone="warm"
              />
              <MetricCard
                label="最近触发"
                value={formatTime(liveOpsSummary.latestTriggeredAtMs)}
                detail="如果长时间没有变化，通常表示没有新 slot 或任务未激活"
                tone="neutral"
              />
            </div>
          </article>

          <article className="sync-status-card">
            <div className="sync-status-head">
              <div>
                <p className="section-eyebrow">Exchange Sync</p>
                <h3>交易所同步</h3>
              </div>
              <span
                className={`status-pill is-${
                  exchangeSyncSummary.blockedReason
                    ? 'error'
                    : exchangeSyncSummary.degraded
                      ? 'warn'
                      : toneForStatus(exchangeSyncSummary.lastStatus)
                }`}
              >
                {exchangeSyncSummary.blockedReason
                  ? '已阻塞'
                  : exchangeSyncSummary.degraded
                    ? '降级中'
                    : describeStatus(exchangeSyncSummary.lastStatus)}
              </span>
            </div>
            <div className="sync-status-metrics">
              <MetricCard
                label="同步循环"
                value={exchangeSyncSummary.loopRunning ? '运行中' : '未运行'}
                detail={
                  exchangeSyncSummary.lastStatus === 'disabled'
                    ? '当前配置未开启 OKX 增量同步'
                    : `最近开始 ${formatTime(exchangeSyncSummary.lastStartedAtMs)}`
                }
                tone={exchangeSyncSummary.loopRunning ? 'accent' : 'neutral'}
              />
              <MetricCard
                label="最近完成"
                value={formatTime(exchangeSyncSummary.lastCompletedAtMs)}
                detail={
                  exchangeSyncSummary.lastStatus === 'disabled'
                    ? '状态 已关闭'
                    : `状态 ${describeStatus(exchangeSyncSummary.lastStatus)}`
                }
                tone="neutral"
              />
              <MetricCard
                label="可派发覆盖"
                value={formatTime(exchangeSyncSummary.dispatchAsOfMs)}
                detail={`覆盖率 ${formatPercent(exchangeSyncSummary.coverageRatio)}`}
                tone="warm"
              />
              <MetricCard
                label="新鲜标的"
                value={`${formatCount(exchangeSyncSummary.freshSymbolCount)} / ${formatCount(exchangeSyncSummary.universeActiveCount)}`}
                detail={`缺失 ${formatCount(exchangeSyncSummary.missingSymbolCount)} / 待补齐 ${formatCount(exchangeSyncSummary.bootstrapPendingCount + exchangeSyncSummary.backfillLagCount)}`}
                tone="neutral"
              />
            </div>
            <div className="sync-health-strip">
              <div className="info-box compact-box">
                <p>快照年龄</p>
                <strong>{formatDuration(exchangeSyncSummary.snapshotAgeMs)}</strong>
              </div>
              <div className="info-box compact-box">
                <p>失败游标</p>
                <strong>{formatCount(failedSyncCount)}</strong>
              </div>
              <div className="info-box compact-box">
                <p>阻塞原因</p>
                <strong>{describeSyncBlockReason(exchangeSyncSummary.blockedReason)}</strong>
              </div>
            </div>
            {showSyncError ? (
              <div className="info-box warning-box">
                <p>最近同步报错</p>
                <small>{exchangeSyncSummary.lastError}</small>
              </div>
            ) : null}
          </article>
        </div>
      </section>

      <section className="dual-grid console-workspace-grid">
        <article className="surface emphasis-surface tall-panel console-editor-surface">
          <PanelHeader title="策略编排台" subtitle="支持 Markdown、AI 推理说明与风险条款，适合直接写中文策略。" />
          <form className="stack" onSubmit={handleUpload}>
            <div className="info-box editor-note">
              <p>提示：直接用中文描述交易想法即可，系统会自动提取执行节奏、工具依赖与风险约束。</p>
            </div>
            <textarea
              value={skillText}
              onChange={(event) => setSkillText(event.target.value)}
              rows={22}
              placeholder="在这里粘贴或撰写你的交易 Skill..."
            />
            <div className="form-footer">
              <p>上传后会生成可回放、可激活实时任务的统一策略版本。</p>
              <button className="action-button is-primary" type="submit" disabled={loading}>
                上传策略
              </button>
            </div>
          </form>
        </article>

        <article className="surface tall-panel">
          <PanelHeader title="执行实验室" subtitle="选择策略、对齐历史覆盖窗口，然后发起回放或进入实时信号阶段。" />
          <div className="stack compact">
            <label>
              <span>当前策略</span>
              <select value={selectedSkill?.id ?? ''} onChange={(event) => setSelectedSkillId(event.target.value)}>
                {skills.length ? (
                  skills.map((skill) => (
                    <option key={skill.id} value={skill.id}>
                      {skill.title}
                    </option>
                  ))
                ) : (
                  <option value="">暂无策略，请先上传</option>
                )}
              </select>
            </label>

              <div className="info-box skill-status-box">
                <div className="info-head">
                  <strong>{selectedSkill?.title ?? '还没有策略版本'}</strong>
                  <span className={`status-pill is-${toneForStatus(selectedSkill?.validation_status)}`}>
                    {selectedSkill ? describeStatus(selectedSkill.validation_status) : '等待创建'}
                  </span>
                </div>
              <p>验证状态：{selectedSkill ? describeStatus(selectedSkill.validation_status) : '--'}</p>
              <p>提取方式：{selectedSkill ? describeExtractionMethod(selectedSkill.extraction_method) : '--'}</p>
              <p>执行节奏：{selectedSkill?.envelope?.trigger?.value ?? '--'}</p>
              <p>
                历史覆盖：{formatTime(marketOverview?.coverage_start_ms)} - {formatTime(marketOverview?.coverage_end_ms)}
              </p>
              <p>工具约束：{(selectedSkill?.envelope?.tool_contract?.required_tools ?? []).join('、') || '系统暂未抽取工具限制'}</p>
              <p>提取说明：{selectedSkill?.envelope?.extraction_meta?.reasoning_summary ?? '当前版本没有额外提取说明。'}</p>
            </div>

            {selectedSkill?.validation_warnings?.length ? (
              <div className="info-box warning-box">
                <p>提取提示</p>
                <small>{selectedSkill.validation_warnings.join('；')}</small>
              </div>
            ) : null}

            <div className="info-box hint-box">
              <p>
                {hasHistoricalCoverage
                  ? '回放时间默认对齐到本地历史覆盖结束点；超出覆盖范围的请求会在创建时直接被拒绝。'
                  : '当前还没有可用的本地历史覆盖，导入 CSV 后才可以发起回放。'}
              </p>
            </div>

            <form className="stack compact" onSubmit={handleBacktest}>
              <div className="field-row">
                <label>
                  <span>回放开始时间</span>
                  <input
                    type="datetime-local"
                    value={backtestStart}
                    onChange={(event) => setBacktestStart(event.target.value)}
                    disabled={!hasHistoricalCoverage}
                  />
                </label>
                <label>
                  <span>回放结束时间</span>
                  <input
                    type="datetime-local"
                    value={backtestEnd}
                    onChange={(event) => setBacktestEnd(event.target.value)}
                    disabled={!hasHistoricalCoverage}
                  />
                </label>
              </div>
              <label>
                <span>初始资金</span>
                <input
                  type="number"
                  min={1000}
                  step={500}
                  value={initialCapital}
                  onChange={(event) => setInitialCapital(Number(event.target.value))}
                  disabled={!hasHistoricalCoverage}
                />
              </label>
              <button className="action-button is-primary" type="submit" disabled={loading || !selectedSkill || !hasHistoricalCoverage}>
                发起回放
              </button>
            </form>

            <div className="divider" />

            <div className="info-box compact-box live-task-box">
              <p>当前实时任务</p>
              <strong>{selectedTask?.id ?? '尚未激活'}</strong>
              <span>
                状态：{selectedTask ? describeStatus(selectedTask.status) : '--'} / 节奏：{selectedTask?.cadence ?? '--'}
              </span>
              <small>上次触发：{formatTime(selectedTask?.last_triggered_at_ms)}</small>
              <small>最近完成 slot：{formatTime(selectedTask?.last_completed_slot_as_of_ms)}</small>
            </div>

            <div className="field-row action-row">
              <button className="action-button" type="button" onClick={handleActivateLiveTask} disabled={loading || !selectedSkill}>
                开启实时任务
              </button>
              <button className="action-button is-primary" type="button" onClick={handleTriggerLiveTask} disabled={loading || !selectedTask}>
                立即触发一次
              </button>
            </div>
          </div>
        </article>
      </section>

      <section className="console-list-grid">
        <article className="surface">
          <PanelHeader title="策略列表" subtitle="查看所有策略版本，并快速切换当前工作对象。" />
          <div className="list-shell">
            {skills.length ? (
              skills.map((skill) => (
                <ListCard
                  key={skill.id}
                  active={selectedSkill?.id === skill.id}
                  title={skill.title}
                  subtitle={describeStatus(skill.validation_status)}
                  meta={`${skill.envelope?.trigger?.value ?? '--'} 节奏 / ${describeExtractionMethod(skill.extraction_method)}`}
                  badge={skill.envelope?.trigger?.value ?? '--'}
                  onClick={() => setSelectedSkillId(skill.id)}
                />
              ))
            ) : (
              <div className="empty-state">
                <p>还没有策略版本，先在左侧编排台上传一份中文策略吧。</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface">
          <PanelHeader title="回放记录" subtitle="选中任意一次回放，即可在下方查看完整执行轨迹。" />
          <div className="list-shell">
            {backtests.length ? (
              backtests.map((run) => {
                const totalReturnPct = typeof run.summary?.total_return_pct === 'number'
                  ? `收益 ${formatPercent(Number(run.summary.total_return_pct))}`
                  : '等待汇总';
                return (
                  <ListCard
                    key={run.id}
                    active={selectedBacktest?.id === run.id}
                    title={run.id}
                    subtitle={`${describeStatus(run.status)} / ${describeScope(run.scope)}`}
                    meta={`${totalReturnPct} / ${formatTime(run.created_at_ms)}`}
                    badge={describeStatus(run.status)}
                    onClick={() => setSelectedBacktestId(run.id)}
                  />
                );
              })
            ) : (
              <div className="empty-state">
                <p>还没有回放记录，先选择策略并发起一次回放。</p>
              </div>
            )}
          </div>
        </article>

        <article className="surface">
          <PanelHeader title="最近信号" subtitle="查看最近一次实时任务输出的交易动作与方向。" />
          <div className="list-shell">
            {signals.length ? (
              signals.map((signal) => {
                const failed = signal.delivery_status === 'failed';
                return (
                  <ListCard
                    key={signal.id}
                    interactive={false}
                    title={signal.signal.symbol ?? (failed ? '执行失败' : describeAction(signal.signal.action) || signal.id)}
                    subtitle={failed
                      ? signal.signal.error_message ?? '请检查 Runner、工具网关或历史数据覆盖。'
                      : `${describeAction(signal.signal.action)} / ${describeDirection(signal.signal.direction)}`}
                    meta={`${describeStatus(signal.delivery_status)} / ${formatTime(signal.trigger_time_ms)}`}
                    badge={describeStatus(signal.delivery_status)}
                  />
                );
              })
            ) : (
              <div className="empty-state">
                <p>暂无实时信号输出，激活任务后这里会持续刷新。</p>
              </div>
            )}
          </div>
        </article>
      </section>

      <section className="stack-section">
        <article className="surface trace-panel">
          <PanelHeader
            title="执行轨迹"
            subtitle="按触发步骤查看 Agent 推理摘要、工具链路与结构化决策。"
            action={
              <button
                className="action-button"
                type="button"
                onClick={() => selectedBacktest?.id && refreshTraceViewer(selectedBacktest.id)}
                disabled={!selectedBacktest?.id || traceLoading}
              >
                {traceLoading ? '轨迹加载中...' : '刷新轨迹'}
              </button>
            }
          />

          {!selectedBacktest ? (
            <div className="empty-state large-empty-state">
              <p>先创建一条回放记录，再从上方回放记录中选中它，这里就会展示逐步执行轨迹。</p>
            </div>
          ) : (
            <>
              <div className="trace-summary-strip">
                <MetricCard label="运行编号" value={selectedBacktest.id} detail="当前正在观察的回放实例" />
                <MetricCard label="运行状态" value={describeStatus(selectedBacktest.status)} detail={describeScope(selectedBacktest.scope)} tone="accent" />
                <MetricCard label="已捕获步骤" value={formatCount(backtestTraces.length)} detail="每个步骤都记录了推理摘要与工具调用" />
                <MetricCard
                  label="总收益"
                  value={typeof selectedBacktest.summary?.total_return_pct === 'number'
                    ? formatPercent(Number(selectedBacktest.summary.total_return_pct))
                    : '--'}
                  detail="回放汇总结果会在任务完成后更新"
                  tone="warm"
                />
              </div>

              <div className="info-box trace-hint-box">
                <p>
                  {traceAutoRefresh
                    ? '当前回放仍在排队或运行中，轨迹会每 2.5 秒自动刷新一次。'
                    : '当前回放已静态完成，你可以展开任意步骤查看工具参数与完整决策 JSON。'}
                </p>
              </div>

              {selectedBacktest.error_message ? (
                <div className="info-box warning-box">
                  <p>{selectedBacktest.error_message}</p>
                </div>
              ) : null}

              {traceError ? (
                <div className="info-box warning-box">
                  <p>{traceError}</p>
                </div>
              ) : null}

              <div className="trace-list">
                {!backtestTraces.length ? (
                  <div className="empty-state large-empty-state">
                    <p>{traceAutoRefresh ? '回放进行中，正在等待第一条轨迹落盘...' : '当前回放还没有保存任何执行步骤。'}</p>
                  </div>
                ) : (
                  backtestTraces.map((trace) => {
                    const rawAction = typeof trace.decision.action === 'string' ? trace.decision.action : 'skip';
                    const simulatedReturn = typeof trace.decision.simulated_return_pct === 'number'
                      ? Number(trace.decision.simulated_return_pct)
                      : null;
                    const llmRounds = trace.llm_rounds ?? [];
                    const executionBreakdown = trace.execution_breakdown ?? null;
                    const hasRuntimeMetrics = Boolean(executionBreakdown || llmRounds.length);

                    return (
                      <article className="trace-card" key={trace.id}>
                        <div className="trace-head">
                          <div>
                            <p className="trace-step-label">第 {trace.trace_index + 1} 步</p>
                            <strong>{formatTime(trace.trigger_time_ms)}</strong>
                          </div>
                          <div className="trace-pill-row">
                            <span className={`status-pill console-action-pill action-${rawAction}`}>{describeAction(rawAction)}</span>
                            {typeof trace.decision.symbol === 'string' ? (
                              <span className="status-pill is-neutral">{trace.decision.symbol}</span>
                            ) : null}
                            <span className="status-pill is-neutral">{trace.tool_calls.length} 个工具</span>
                            <span className="status-pill is-neutral">
                              模型推理/等待 {formatShortDuration(executionBreakdown?.llm_wait_total_ms)}
                            </span>
                            <span className="status-pill is-neutral">
                              工具执行 {formatShortDuration(executionBreakdown?.tool_execution_total_ms)}
                            </span>
                            <span className="status-pill is-neutral">
                              总耗时 {formatShortDuration(trace.execution_timing?.duration_ms)}
                            </span>
                            {simulatedReturn !== null ? (
                              <span className={`status-pill ${simulatedReturn >= 0 ? 'is-ok' : 'is-error'}`}>
                                {formatPercent(simulatedReturn)}
                              </span>
                            ) : null}
                          </div>
                        </div>

                        <p className="trace-summary-text">{trace.reasoning_summary || '本步骤未返回推理摘要。'}</p>

                        <div className="trace-meta-grid">
                          <div className="info-box compact-box">
                            <p>决策摘要</p>
                            <strong className="mini-metric">{summarizeDecision(trace.decision)}</strong>
                          </div>
                          <div className="info-box compact-box">
                            <p>工具序列</p>
                            <strong className="mini-metric">{summarizeToolSequence(trace.tool_calls)}</strong>
                          </div>
                        </div>

                        {trace.tool_calls.length ? (
                          <details className="trace-details">
                            <summary>查看工具调用</summary>
                            <div className="trace-details-body">
                              {trace.tool_calls.map((call, index) => (
                                <div className="trace-tool-row" key={`${trace.id}-${call.tool_name}-${index}`}>
                                  <div className="trace-tool-head">
                                    <strong>
                                      {index + 1}. {call.tool_name}
                                    </strong>
                                    <span>{describeStatus(call.status)}</span>
                                  </div>
                                  <div className="trace-tool-meta-grid">
                                    <div className="info-box compact-box">
                                      <p>实际执行时间</p>
                                      <strong className="mini-metric">{formatPreciseTime(call.execution_timing?.started_at_ms)}</strong>
                                    </div>
                                    <div className="info-box compact-box">
                                      <p>耗时</p>
                                      <strong className="mini-metric">{formatShortDuration(call.execution_timing?.duration_ms)}</strong>
                                    </div>
                                  </div>
                                  <pre className="json-block">{formatJson(call.arguments)}</pre>
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : null}

                        {hasRuntimeMetrics ? (
                          <details className="trace-details">
                            <summary>查看模型轮次</summary>
                            <div className="trace-details-body">
                              <div className="trace-tool-meta-grid">
                                <div className="info-box compact-box">
                                  <p>模型推理/等待</p>
                                  <strong className="mini-metric">{formatShortDuration(executionBreakdown?.llm_wait_total_ms)}</strong>
                                </div>
                                <div className="info-box compact-box">
                                  <p>其他开销</p>
                                  <strong className="mini-metric">{formatShortDuration(executionBreakdown?.other_overhead_ms)}</strong>
                                </div>
                              </div>

                              {llmRounds.length ? (
                                <div className="trace-round-list">
                                  {llmRounds.map((round) => (
                                    <div className="trace-round-row" key={`${trace.id}-round-${round.round_index}`}>
                                      <div className="trace-round-head">
                                        <strong>第 {round.round_index} 轮</strong>
                                        <span>{describeLlmRoundResult(round.result_type)}</span>
                                      </div>
                                      <div className="trace-round-meta-grid">
                                        <div className="info-box compact-box">
                                          <p>轮次耗时</p>
                                          <strong className="mini-metric">{formatShortDuration(round.llm_round_duration_ms)}</strong>
                                        </div>
                                        <div className="info-box compact-box">
                                          <p>工具调用数</p>
                                          <strong className="mini-metric">{formatCount(round.tool_call_count)}</strong>
                                        </div>
                                        <div className="info-box compact-box">
                                          <p>开始时间</p>
                                          <strong className="mini-metric">{formatPreciseTime(round.started_at_ms)}</strong>
                                        </div>
                                        <div className="info-box compact-box">
                                          <p>结束时间</p>
                                          <strong className="mini-metric">{formatPreciseTime(round.completed_at_ms)}</strong>
                                        </div>
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              ) : (
                                <div className="empty-state compact-empty">
                                  <p>当前轨迹没有可用的模型轮次明细。</p>
                                </div>
                              )}
                            </div>
                          </details>
                        ) : null}

                        <details className="trace-details">
                          <summary>查看完整决策 JSON</summary>
                          <pre className="json-block">{formatJson(trace.decision)}</pre>
                        </details>
                      </article>
                    );
                  })
                )}
              </div>
            </>
          )}
        </article>
      </section>
    </div>
  );
}
