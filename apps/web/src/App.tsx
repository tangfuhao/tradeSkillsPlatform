import { FormEvent, useEffect, useMemo, useState } from 'react';

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
  updateSkillReviewState,
} from './api';
import type {
  BacktestRun,
  BacktestTrace,
  LiveSignal,
  LiveTask,
  MarketOverview,
  ReviewStatus,
  ServicePulse,
  Skill,
  ToolCall,
} from './types';

const defaultSkill = `# Short-Term Overheat Short Skill

## Execution Cadence
Every 15 minutes.

## Step 1 - Market Scan
Scan OKX USDT perpetual swap instruments and rank candidates by strong short-term upside extension, rising speculative activity, and liquid trading volume.

## Step 2 - Market Data Collection
Fetch 15m and 4h candles for the best candidates and compute EMA20, EMA60, RSI14, and ATR14.
Fetch funding rate and open interest change when available.

## Step 3 - AI Reasoning
You are an AI trading agent. Reason about which altcoin looks the most overheated for a short setup.
If market structure is unclear, skip the cycle.

## Step 4 - Signal Output
If confidence is high, open a short setup with at most 10 percent of equity.

## Risk Control
- Every position must define a stop loss at 2 percent.
- Initial take profit target is 10 percent.
- Max daily drawdown is 8 percent.
- Max concurrent positions is 2.
- Hedging is not allowed.`;

function toDateTimeLocal(value: Date): string {
  const offset = value.getTimezoneOffset();
  const local = new Date(value.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function formatTime(value?: string | null): string {
  if (!value) return '--';
  return new Date(value).toLocaleString();
}

function formatCount(value?: number | null): string {
  if (typeof value !== 'number') return '--';
  return new Intl.NumberFormat().format(value);
}

function formatPercent(value?: number | null): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '--';
  return `${(value * 100).toFixed(2)}%`;
}

function describeReviewStatus(status?: ReviewStatus): string {
  if (status === 'approved_full_window') return 'approved for larger history windows';
  if (status === 'review_pending') return 'awaiting operator review';
  if (status === 'review_rejected') return 'rejected for extended history';
  return 'preview-ready for the default recent window';
}

function summarizeDecision(decision: Record<string, unknown>): string {
  const action = typeof decision.action === 'string' ? decision.action : 'skip';
  const symbol = typeof decision.symbol === 'string' ? decision.symbol : null;
  const direction = typeof decision.direction === 'string' ? decision.direction : null;
  const sizePct = typeof decision.size_pct === 'number' ? formatPercent(decision.size_pct) : null;
  return [action, symbol, direction, sizePct].filter(Boolean).join(' / ');
}

function summarizeToolSequence(toolCalls: ToolCall[]): string {
  if (!toolCalls.length) return 'No tool calls recorded';
  return toolCalls.map((call) => call.tool_name).join(' -> ');
}

function formatJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function isBacktestActive(status?: string): boolean {
  return status === 'queued' || status === 'running';
}

export default function App() {
  const [skillText, setSkillText] = useState(defaultSkill);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [backtests, setBacktests] = useState<BacktestRun[]>([]);
  const [liveTasks, setLiveTasks] = useState<LiveTask[]>([]);
  const [signals, setSignals] = useState<LiveSignal[]>([]);
  const [servicePulse, setServicePulse] = useState<ServicePulse[]>([]);
  const [marketOverview, setMarketOverview] = useState<MarketOverview | null>(null);
  const [selectedSkillId, setSelectedSkillId] = useState('');
  const [selectedTaskId, setSelectedTaskId] = useState('');
  const [selectedBacktestId, setSelectedBacktestId] = useState('');
  const [backtestTraces, setBacktestTraces] = useState<BacktestTrace[]>([]);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState<string | null>(null);
  const [message, setMessage] = useState('Ready to orchestrate a Skill.');
  const [loading, setLoading] = useState(false);
  const [backtestStart, setBacktestStart] = useState(toDateTimeLocal(new Date(Date.now() - 24 * 60 * 60 * 1000)));
  const [backtestEnd, setBacktestEnd] = useState(toDateTimeLocal(new Date()));
  const [initialCapital, setInitialCapital] = useState(10000);

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
  const traceAutoRefresh = isBacktestActive(selectedBacktest?.status);

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
      { name: 'API', status: apiHealth.status, details: getApiBaseUrl() },
      { name: 'Agent Runner', status: runnerHealth.status, details: getAgentRunnerBaseUrl() },
    ]);
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
      setTraceError(`Trace fetch failed: ${String(error)}`);
    } finally {
      if (!silent) {
        setTraceLoading(false);
      }
    }
  }

  useEffect(() => {
    refreshDashboard().catch((error) => {
      setMessage(`Bootstrap check failed: ${String(error)}`);
    });
  }, []);

  useEffect(() => {
    if (!selectedBacktest?.id) {
      setBacktestTraces([]);
      setTraceError(null);
      return;
    }
    refreshTraceViewer(selectedBacktest.id).catch((error) => {
      setTraceError(`Trace fetch failed: ${String(error)}`);
    });
  }, [selectedBacktest?.id]);

  useEffect(() => {
    if (!selectedBacktest?.id || !traceAutoRefresh) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      Promise.all([refreshDashboard(), refreshTraceViewer(selectedBacktest.id, true)]).catch((error) => {
        setTraceError(`Trace refresh failed: ${String(error)}`);
      });
    }, 2500);
    return () => window.clearInterval(timer);
  }, [selectedBacktest?.id, traceAutoRefresh]);

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setLoading(true);
    setMessage('Uploading Skill and extracting its runtime envelope...');
    try {
      const created = await createSkill({ skill_text: skillText });
      setSelectedSkillId(created.id);
      setMessage(`Skill ${created.title} is now preview-ready.`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`Skill upload failed: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleBacktest(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedSkill) {
      setMessage('Create or select a Skill before launching a backtest.');
      return;
    }
    setLoading(true);
    setMessage('Queueing a replay-based backtest run...');
    try {
      const created = await createBacktest({
        skill_id: selectedSkill.id,
        start_time: new Date(backtestStart).toISOString(),
        end_time: new Date(backtestEnd).toISOString(),
        initial_capital: initialCapital,
      });
      setSelectedBacktestId(created.id);
      setBacktestTraces([]);
      setTraceError(null);
      setMessage(`Backtest ${created.id} is queued. Trace Viewer will auto-refresh while it runs.`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`Backtest creation failed: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleReviewUpdate(reviewStatus: ReviewStatus) {
    if (!selectedSkill) {
      setMessage('Select a Skill before changing review state.');
      return;
    }
    setLoading(true);
    setMessage(`Updating review state for ${selectedSkill.title}...`);
    try {
      const updated = await updateSkillReviewState(selectedSkill.id, reviewStatus);
      setSelectedSkillId(updated.id);
      setMessage(`Skill ${updated.title} is now ${describeReviewStatus(updated.review_status)}.`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`Review state update failed: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleActivateLiveTask() {
    if (!selectedSkill) {
      setMessage('Create or select a Skill before activating live mode.');
      return;
    }
    setLoading(true);
    setMessage('Activating a live signal task from the Skill cadence...');
    try {
      const created = await createLiveTask({ skill_id: selectedSkill.id });
      setSelectedTaskId(created.id);
      setMessage(`Live task ${created.id} is active on cadence ${created.cadence}.`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`Live task activation failed: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  async function handleTriggerLiveTask() {
    if (!selectedTask) {
      setMessage('Activate a live task before triggering one manually.');
      return;
    }
    setLoading(true);
    setMessage('Running a short-lived live signal task now...');
    try {
      await triggerLiveTask(selectedTask.id);
      setMessage(`Live task ${selectedTask.id} emitted a new stored signal.`);
      await refreshDashboard();
    } catch (error) {
      setMessage(`Manual live trigger failed: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="shell">
      <header className="hero">
        <div>
          <p className="eyebrow">Skill-Driven Agent Runtime</p>
          <h1>TradeSkills Demo Console</h1>
          <p className="hero-copy">
            Upload a natural-language trading Skill, extract a Skill Envelope, replay it against local OKX history,
            or activate a live periodic signal loop from the same runtime contract.
          </p>
        </div>
        <div className="status-ribbon">
          <span className="status-dot" />
          <span>{loading ? 'Processing...' : message}</span>
        </div>
      </header>

      <section className="grid two-up">
        <article className="panel pulse-panel">
          <div className="panel-header">
            <h2>Service Pulse</h2>
            <button type="button" onClick={() => refreshDashboard().catch((error) => setMessage(String(error)))}>
              Refresh
            </button>
          </div>
          <div className="pulse-grid">
            {servicePulse.map((item) => (
              <div className="pulse-card" key={item.name}>
                <p>{item.name}</p>
                <strong>{item.status}</strong>
                <span>{item.details}</span>
              </div>
            ))}
          </div>
        </article>

        <article className="panel insight-panel">
          <div className="panel-header">
            <h2>Market Coverage</h2>
            <span>Blocking startup sync + dynamic timeframe aggregation</span>
          </div>
          <div className="insight-grid">
            <div>
              <span>Symbols</span>
              <strong>{formatCount(marketOverview?.total_symbols)}</strong>
            </div>
            <div>
              <span>1m Bars</span>
              <strong>{formatCount(marketOverview?.total_candles)}</strong>
            </div>
            <div>
              <span>Coverage Start</span>
              <strong className="mini-metric">{formatTime(marketOverview?.coverage_start)}</strong>
            </div>
            <div>
              <span>Coverage End</span>
              <strong className="mini-metric">{formatTime(marketOverview?.coverage_end)}</strong>
            </div>
          </div>
          <div className="meta-strip">
            <div className="info-box compact-box">
              <p>Base timeframe</p>
              <strong>{marketOverview?.base_timeframe ?? '--'}</strong>
            </div>
            <div className="info-box compact-box">
              <p>Latest seed import</p>
              <strong>{latestCsvJob ? `${formatCount(latestCsvJob.rows_inserted)} rows` : '--'}</strong>
            </div>
            <div className="info-box compact-box">
              <p>API sync skips</p>
              <strong>{formatCount(skippedSyncCount)}</strong>
            </div>
          </div>
        </article>
      </section>

      <section className="grid main-grid">
        <article className="panel tall-panel">
          <div className="panel-header">
            <h2>Skill Composer</h2>
            <span>Markdown + AI reasoning + risk control</span>
          </div>
          <form className="stack" onSubmit={handleUpload}>
            <textarea value={skillText} onChange={(event) => setSkillText(event.target.value)} rows={22} />
            <button className="primary-button" type="submit" disabled={loading}>
              Upload Skill
            </button>
          </form>
        </article>

        <article className="panel tall-panel">
          <div className="panel-header">
            <h2>Run Lab</h2>
            <span>Replay first, then live signal activation</span>
          </div>
          <div className="stack compact">
            <label>
              <span>Selected Skill</span>
              <select value={selectedSkill?.id ?? ''} onChange={(event) => setSelectedSkillId(event.target.value)}>
                {skills.map((skill) => (
                  <option key={skill.id} value={skill.id}>
                    {skill.title}
                  </option>
                ))}
              </select>
            </label>

            <div className="info-box skill-status-box">
              <strong>{selectedSkill?.title ?? 'No Skill yet'}</strong>
              <p>
                Cadence: {selectedSkill?.envelope?.trigger?.value ?? '--'} | Review: {selectedSkill?.review_status ?? '--'}
              </p>
              <p>
                Preview window: {formatTime(selectedSkill?.preview_window?.start)} -{' '}
                {formatTime(selectedSkill?.preview_window?.end)}
              </p>
              <p>
                Tools: {(selectedSkill?.envelope?.tool_contract?.required_tools ?? []).join(', ') || '--'}
              </p>
            </div>

            <div className="field-row action-row">
              <button
                className="secondary-button"
                type="button"
                onClick={() => handleReviewUpdate('preview_ready')}
                disabled={loading || !selectedSkill}
              >
                Mark Preview
              </button>
              <button
                className="primary-button"
                type="button"
                onClick={() => handleReviewUpdate('approved_full_window')}
                disabled={loading || !selectedSkill}
              >
                Approve Full Window
              </button>
            </div>

            <div className="info-box hint-box">
              <p>
                Preview-ready Skills are restricted to the recent default window. Use full-window approval before replaying
                older seeded history, especially when your local CSV coverage does not overlap the latest 90 days.
              </p>
            </div>

            <form className="stack compact" onSubmit={handleBacktest}>
              <div className="field-row">
                <label>
                  <span>Backtest Start</span>
                  <input type="datetime-local" value={backtestStart} onChange={(event) => setBacktestStart(event.target.value)} />
                </label>
                <label>
                  <span>Backtest End</span>
                  <input type="datetime-local" value={backtestEnd} onChange={(event) => setBacktestEnd(event.target.value)} />
                </label>
              </div>
              <label>
                <span>Initial Capital</span>
                <input
                  type="number"
                  min={1000}
                  step={500}
                  value={initialCapital}
                  onChange={(event) => setInitialCapital(Number(event.target.value))}
                />
              </label>
              <button className="primary-button" type="submit" disabled={loading || !selectedSkill}>
                Launch Backtest
              </button>
            </form>

            <div className="divider" />

            <div className="field-row action-row">
              <button className="secondary-button" type="button" onClick={handleActivateLiveTask} disabled={loading || !selectedSkill}>
                Activate Live Task
              </button>
              <button className="primary-button" type="button" onClick={handleTriggerLiveTask} disabled={loading || !selectedTask}>
                Trigger Live Now
              </button>
            </div>
          </div>
        </article>
      </section>

      <section className="grid three-up">
        <article className="panel">
          <div className="panel-header">
            <h2>Skills</h2>
          </div>
          <div className="list-shell">
            {skills.map((skill) => (
              <button
                className={`list-card ${selectedSkill?.id === skill.id ? 'selected-card' : ''}`}
                key={skill.id}
                type="button"
                onClick={() => setSelectedSkillId(skill.id)}
              >
                <strong>{skill.title}</strong>
                <span>{describeReviewStatus(skill.review_status)}</span>
                <small>{skill.envelope?.trigger?.value ?? '--'} cadence</small>
              </button>
            ))}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <h2>Backtest Feed</h2>
            <span>Pick one to inspect its trace</span>
          </div>
          <div className="list-shell">
            {backtests.map((run) => {
              const totalReturnPct = typeof run.summary?.total_return_pct === 'number'
                ? `${(Number(run.summary.total_return_pct) * 100).toFixed(2)}%`
                : 'Waiting for summary';
              return (
                <button
                  className={`list-card ${selectedBacktest?.id === run.id ? 'selected-card' : ''}`}
                  key={run.id}
                  type="button"
                  onClick={() => setSelectedBacktestId(run.id)}
                >
                  <strong>{run.id}</strong>
                  <span>
                    {run.status} / {run.scope}
                  </span>
                  <small>{totalReturnPct}</small>
                </button>
              );
            })}
          </div>
        </article>

        <article className="panel">
          <div className="panel-header">
            <h2>Recent Signals</h2>
          </div>
          <div className="list-shell">
            {signals.map((signal) => (
              <div className="list-card static" key={signal.id}>
                <strong>{signal.signal.symbol ?? signal.signal.action ?? signal.id}</strong>
                <span>
                  {signal.signal.action ?? '--'} / {signal.signal.direction ?? '--'}
                </span>
                <small>{formatTime(signal.trigger_time)}</small>
              </div>
            ))}
          </div>
        </article>
      </section>

      <section className="grid">
        <article className="panel">
          <div className="panel-header">
            <div>
              <h2>Execution Trace</h2>
              <span>Observe each replay trigger, tool sequence, and structured decision.</span>
            </div>
            <button
              type="button"
              onClick={() => selectedBacktest?.id && refreshTraceViewer(selectedBacktest.id)}
              disabled={!selectedBacktest?.id || traceLoading}
            >
              {traceLoading ? 'Loading...' : 'Refresh Trace'}
            </button>
          </div>

          {!selectedBacktest ? (
            <div className="info-box">
              <p>Create a backtest first, then select it from Backtest Feed to inspect the Agent run step by step.</p>
            </div>
          ) : (
            <>
              <div className="trace-summary-strip">
                <div className="info-box compact-box">
                  <p>Run ID</p>
                  <strong>{selectedBacktest.id}</strong>
                </div>
                <div className="info-box compact-box">
                  <p>Status</p>
                  <strong>{selectedBacktest.status}</strong>
                </div>
                <div className="info-box compact-box">
                  <p>Steps Captured</p>
                  <strong>{formatCount(backtestTraces.length)}</strong>
                </div>
                <div className="info-box compact-box">
                  <p>Return</p>
                  <strong>
                    {typeof selectedBacktest.summary?.total_return_pct === 'number'
                      ? formatPercent(Number(selectedBacktest.summary.total_return_pct))
                      : '--'}
                  </strong>
                </div>
              </div>

              <div className="info-box trace-hint-box">
                <p>
                  {traceAutoRefresh
                    ? 'Auto-refresh is active every 2.5 seconds while this backtest is queued or running.'
                    : 'Trace capture is static now. Expand any step to inspect tool arguments and the final decision payload.'}
                </p>
              </div>

              {traceError ? (
                <div className="info-box warning-box">
                  <p>{traceError}</p>
                </div>
              ) : null}

              <div className="trace-list">
                {!backtestTraces.length ? (
                  <div className="info-box">
                    <p>
                      {traceAutoRefresh
                        ? 'Backtest is running. Waiting for the first saved trace step...'
                        : 'No trace steps are stored for this run yet.'}
                    </p>
                  </div>
                ) : (
                  backtestTraces.map((trace) => {
                    const simulatedReturn = typeof trace.decision.simulated_return_pct === 'number'
                      ? Number(trace.decision.simulated_return_pct)
                      : null;
                    return (
                      <article className="trace-card" key={trace.id}>
                        <div className="trace-head">
                          <div>
                            <p className="trace-step-label">Step {trace.trace_index + 1}</p>
                            <strong>{formatTime(trace.trigger_time)}</strong>
                          </div>
                          <div className="trace-pill-row">
                            <span className={`status-chip action-chip action-${String(trace.decision.action ?? 'skip')}`}>
                              {String(trace.decision.action ?? 'skip')}
                            </span>
                            {typeof trace.decision.symbol === 'string' ? (
                              <span className="status-chip neutral-chip">{trace.decision.symbol}</span>
                            ) : null}
                            <span className="status-chip neutral-chip">{trace.tool_calls.length} tools</span>
                            {simulatedReturn !== null ? (
                              <span className={`status-chip ${simulatedReturn >= 0 ? 'good-chip' : 'bad-chip'}`}>
                                {formatPercent(simulatedReturn)}
                              </span>
                            ) : null}
                          </div>
                        </div>

                        <p className="trace-summary-text">{trace.reasoning_summary}</p>

                        <div className="trace-meta-grid">
                          <div className="info-box compact-box">
                            <p>Decision</p>
                            <strong className="mini-metric">{summarizeDecision(trace.decision)}</strong>
                          </div>
                          <div className="info-box compact-box">
                            <p>Tool Sequence</p>
                            <strong className="mini-metric">{summarizeToolSequence(trace.tool_calls)}</strong>
                          </div>
                        </div>

                        {trace.tool_calls.length ? (
                          <details className="trace-details">
                            <summary>Tool calls</summary>
                            <div className="trace-details-body">
                              {trace.tool_calls.map((call, index) => (
                                <div className="trace-tool-row" key={`${trace.id}-${call.tool_name}-${index}`}>
                                  <div className="trace-tool-head">
                                    <strong>
                                      {index + 1}. {call.tool_name}
                                    </strong>
                                    <span>{call.status}</span>
                                  </div>
                                  <pre className="json-block">{formatJson(call.arguments)}</pre>
                                </div>
                              ))}
                            </div>
                          </details>
                        ) : null}

                        <details className="trace-details">
                          <summary>Full decision JSON</summary>
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
