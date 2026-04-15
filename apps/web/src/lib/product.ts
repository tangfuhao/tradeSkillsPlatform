import type { BacktestRun, LiveSignal, LiveTask, PortfolioState, Skill } from '../types';

export type SignalFeedItem = {
  signal: LiveSignal;
  liveTask: LiveTask | null;
  skill: Skill | null;
};

export type PortfolioByTaskId = Record<string, PortfolioState>;

export type StrategyInsight = {
  skill: Skill;
  liveTasks: LiveTask[];
  liveTask: LiveTask | null;
  livePortfolio: PortfolioState | null;
  signals: LiveSignal[];
  backtests: BacktestRun[];
  latestSignal: LiveSignal | null;
  latestBacktest: BacktestRun | null;
  activeBacktestCount: number;
  completedBacktestCount: number;
  recentSymbols: string[];
  lastActivityMs: number;
};

function sortByDescendingTime<T>(items: T[], getTime: (item: T) => number): T[] {
  return [...items].sort((left, right) => getTime(right) - getTime(left));
}

export function getLiveTaskActivityMs(task: LiveTask): number {
  return task.last_activity_at_ms ?? Math.max(task.last_triggered_at_ms ?? 0, task.updated_at_ms, task.created_at_ms);
}

export function getBacktestActivityMs(run: BacktestRun): number {
  return run.last_activity_at_ms ?? Math.max(run.updated_at_ms, run.created_at_ms);
}

function toSymbolList(signals: LiveSignal[]): string[] {
  const uniqueSymbols = new Set<string>();

  signals.forEach((signal) => {
    const symbol = signal.signal.symbol?.trim();
    if (symbol) {
      uniqueSymbols.add(symbol);
    }
  });

  return Array.from(uniqueSymbols);
}

export function getSkillCadence(skill: Skill): string {
  return skill.envelope.trigger?.value ?? '--';
}

export function getStrategyExcerpt(skill: Skill): string {
  const summary = skill.envelope.extraction_meta?.reasoning_summary?.trim();
  if (summary) return summary;
  if (skill.validation_warnings.length) return skill.validation_warnings.join('；');
  if (skill.validation_errors.length) return skill.validation_errors.join('；');
  return '策略已被冻结为可执行版本，可直接用于回测与实时模拟。';
}

export function getRunReturnPct(run: BacktestRun | null): number | null {
  if (!run) return null;
  const value = run.summary?.total_return_pct;
  return typeof value === 'number' ? Number(value) : null;
}

export function getRunNetPnl(run: BacktestRun | null): number | null {
  if (!run) return null;
  const value = run.summary?.net_pnl;
  return typeof value === 'number' ? Number(value) : null;
}

export function getProgressPercent(run: BacktestRun): number {
  return run.progress?.percent ?? 0;
}

export function getProgressLabel(run: BacktestRun): string {
  const completed = run.progress?.completed_steps ?? 0;
  const total = run.progress?.total_steps ?? 0;
  if (!total) return '等待执行';
  return `${completed}/${total}`;
}

export function buildSignalFeed(signals: LiveSignal[], liveTasks: LiveTask[], skills: Skill[]): SignalFeedItem[] {
  const liveTaskById = new Map(liveTasks.map((task) => [task.id, task]));
  const skillById = new Map(skills.map((skill) => [skill.id, skill]));

  return sortByDescendingTime(signals, (signal) => signal.trigger_time_ms).map((signal) => {
    const liveTask = liveTaskById.get(signal.live_task_id) ?? null;
    const skill = liveTask ? skillById.get(liveTask.skill_id) ?? null : null;

    return {
      signal,
      liveTask,
      skill,
    };
  });
}

export function buildStrategyInsights(
  skills: Skill[],
  liveTasks: LiveTask[],
  signals: LiveSignal[],
  backtests: BacktestRun[],
  portfoliosByTaskId: PortfolioByTaskId = {},
): StrategyInsight[] {
  const liveTasksBySkillId = new Map<string, LiveTask[]>();
  const signalsBySkillId = new Map<string, LiveSignal[]>();
  const backtestsBySkillId = new Map<string, BacktestRun[]>();
  const liveTaskById = new Map(liveTasks.map((task) => [task.id, task]));

  liveTasks.forEach((task) => {
    const taskList = liveTasksBySkillId.get(task.skill_id) ?? [];
    taskList.push(task);
    liveTasksBySkillId.set(task.skill_id, taskList);
  });

  signals.forEach((signal) => {
    const liveTask = liveTaskById.get(signal.live_task_id);
    if (!liveTask) return;

    const signalList = signalsBySkillId.get(liveTask.skill_id) ?? [];
    signalList.push(signal);
    signalsBySkillId.set(liveTask.skill_id, signalList);
  });

  backtests.forEach((run) => {
    const runList = backtestsBySkillId.get(run.skill_id) ?? [];
    runList.push(run);
    backtestsBySkillId.set(run.skill_id, runList);
  });

  return sortByDescendingTime(
    skills.map((skill) => {
      const relatedLiveTasks = sortByDescendingTime(liveTasksBySkillId.get(skill.id) ?? [], getLiveTaskActivityMs);
      const relatedSignals = sortByDescendingTime(signalsBySkillId.get(skill.id) ?? [], (signal) => signal.trigger_time_ms);
      const relatedBacktests = sortByDescendingTime(backtestsBySkillId.get(skill.id) ?? [], getBacktestActivityMs);
      const liveTask =
        relatedLiveTasks.find((task) => task.status === 'active' || task.status === 'paused') ?? relatedLiveTasks[0] ?? null;
      const livePortfolio = liveTask ? portfoliosByTaskId[liveTask.id] ?? null : null;
      const latestSignal = relatedSignals[0] ?? null;
      const latestBacktest = relatedBacktests[0] ?? null;
      const recentSymbols = toSymbolList(relatedSignals);
      const lastActivityMs = Math.max(
        skill.updated_at_ms,
        liveTask ? getLiveTaskActivityMs(liveTask) : 0,
        latestSignal?.trigger_time_ms ?? 0,
        latestBacktest ? getBacktestActivityMs(latestBacktest) : 0,
        livePortfolio?.account?.last_mark_time_ms ?? 0,
      );

      return {
        skill,
        liveTasks: relatedLiveTasks,
        liveTask,
        livePortfolio,
        signals: relatedSignals,
        backtests: relatedBacktests,
        latestSignal,
        latestBacktest,
        activeBacktestCount: relatedBacktests.filter((run) => ['queued', 'running', 'paused', 'stopping'].includes(run.status)).length,
        completedBacktestCount: relatedBacktests.filter((run) => run.status === 'completed').length,
        recentSymbols,
        lastActivityMs,
      } satisfies StrategyInsight;
    }),
    (insight) => insight.lastActivityMs,
  );
}
