import type { BacktestRun, LiveSignal, LiveTask, Skill } from '../types';

export type SignalFeedItem = {
  signal: LiveSignal;
  liveTask: LiveTask | null;
  skill: Skill | null;
};

export type StrategyInsight = {
  skill: Skill;
  liveTasks: LiveTask[];
  signals: LiveSignal[];
  backtests: BacktestRun[];
  latestLiveTask: LiveTask | null;
  latestSignal: LiveSignal | null;
  latestBacktest: BacktestRun | null;
  activeTaskCount: number;
  recentSymbols: string[];
  lastActivityMs: number;
};

function sortByDescendingTime<T>(items: T[], getTime: (item: T) => number): T[] {
  return [...items].sort((left, right) => getTime(right) - getTime(left));
}

function getLiveTaskActivityMs(task: LiveTask): number {
  return Math.max(task.last_triggered_at_ms ?? 0, task.updated_at_ms, task.created_at_ms);
}

function getBacktestActivityMs(run: BacktestRun): number {
  return Math.max(run.updated_at_ms, run.created_at_ms);
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
  return '该策略已经整理成产品可读资料卡，可直接理解执行节奏、工具限制与风险约束。';
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

  const insights = skills.map((skill) => {
    const relatedLiveTasks = sortByDescendingTime(liveTasksBySkillId.get(skill.id) ?? [], getLiveTaskActivityMs);
    const relatedSignals = sortByDescendingTime(signalsBySkillId.get(skill.id) ?? [], (signal) => signal.trigger_time_ms);
    const relatedBacktests = sortByDescendingTime(backtestsBySkillId.get(skill.id) ?? [], getBacktestActivityMs);

    const latestLiveTask = relatedLiveTasks[0] ?? null;
    const latestSignal = relatedSignals[0] ?? null;
    const latestBacktest = relatedBacktests[0] ?? null;
    const activeTaskCount = relatedLiveTasks.filter((task) => task.status === 'active' || task.status === 'running').length;
    const recentSymbols = toSymbolList(relatedSignals);
    const lastActivityMs = Math.max(
      skill.updated_at_ms,
      latestSignal?.trigger_time_ms ?? 0,
      latestLiveTask ? getLiveTaskActivityMs(latestLiveTask) : 0,
      latestBacktest ? getBacktestActivityMs(latestBacktest) : 0,
    );

    return {
      skill,
      liveTasks: relatedLiveTasks,
      signals: relatedSignals,
      backtests: relatedBacktests,
      latestLiveTask,
      latestSignal,
      latestBacktest,
      activeTaskCount,
      recentSymbols,
      lastActivityMs,
    };
  });

  return sortByDescendingTime(insights, (insight) => insight.lastActivityMs);
}
