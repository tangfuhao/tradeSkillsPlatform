import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';

import LifecycleActions from '../components/LifecycleActions';
import ProductStatTile from '../components/ProductStatTile';
import { controlBacktest, deleteBacktest, listBacktests, listSkills } from '../api';
import {
  describeStatus,
  formatCount,
  formatSignedPercent,
  formatTime,
  formatWindow,
  getErrorMessage,
  toneForStatus,
} from '../lib/formatting';
import { getProgressLabel, getRunReturnPct } from '../lib/product';
import type { BacktestRun, ExecutionAction, Skill } from '../types';

type ReplayData = {
  backtests: BacktestRun[];
  skills: Skill[];
};

function progressWidth(run: BacktestRun): string {
  return `${Math.round((run.progress?.percent ?? 0) * 100)}%`;
}

export default function ReplayHubPage() {
  const [data, setData] = useState<ReplayData>({ backtests: [], skills: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [backtests, skills] = await Promise.all([listBacktests(), listSkills()]);
      setData({ backtests, skills });
      setError(null);
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => {
      void load();
    }, 15000);
    return () => window.clearInterval(timer);
  }, [load]);

  const skillById = useMemo(() => new Map(data.skills.map((skill) => [skill.id, skill])), [data.skills]);

  const stats = useMemo(
    () => [
      {
        label: '全部回测',
        value: formatCount(data.backtests.length),
        detail: data.backtests[0] ? `最新 ${data.backtests[0].id}` : '暂无回测',
      },
      {
        label: '运行中',
        value: formatCount(data.backtests.filter((run) => ['queued', 'running', 'paused', 'stopping'].includes(run.status)).length),
        detail: '支持暂停 / 继续 / 停止 / 删除',
      },
      {
        label: '已完成',
        value: formatCount(data.backtests.filter((run) => run.status === 'completed').length),
        detail: '已完成回测保留结果与时间线',
      },
      {
        label: '失败/停止',
        value: formatCount(data.backtests.filter((run) => run.status === 'failed' || run.status === 'stopped').length),
        detail: '失败与中断回测可直接清理',
      },
    ],
    [data.backtests],
  );

  async function handleAction(run: BacktestRun, action: ExecutionAction) {
    if (action === 'delete') {
      const confirmed = window.confirm(`删除回测 ${run.id}？\n\n这会同时删除该回测的 traces、组合状态和执行细节。`);
      if (!confirmed) return;
    }
    if (action === 'stop') {
      const confirmed = window.confirm(`停止回测 ${run.id}？\n\n当前进度会保留，后续可删除。`);
      if (!confirmed) return;
    }

    const key = `${run.id}:${action}`;
    setPendingKey(key);
    try {
      if (action === 'delete') {
        await deleteBacktest(run.id);
      } else {
        await controlBacktest(run.id, action);
      }
      await load();
    } catch (nextError) {
      setError(getErrorMessage(nextError));
    } finally {
      setPendingKey(null);
    }
  }

  return (
    <div className="page-stack">
      <section className="hero-panel surface">
        <div>
          <p className="section-eyebrow">Backtest Operations</p>
          <h1>把回测列表改成操作面板，而不是只读剧场。</h1>
          <p className="hero-copy">
            每条回测都直接暴露状态、进度、执行窗口、结果与可用动作；回测详情页则专注当前 run，而不是竞争性地展示其它列表。
          </p>
        </div>
        <div className="hero-meta">
          <span className="info-pill">支持暂停 / 继续 / 停止 / 删除</span>
          <Link className="action-button is-primary" to="/strategies">
            去策略页发起新回测
          </Link>
        </div>
      </section>

      <section className="metric-grid">
        {stats.map((stat) => (
          <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
        ))}
      </section>

      {error ? <div className="feedback-banner is-error">回测列表加载失败：{error}</div> : null}

      <section className="surface">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">Replay Records</p>
            <h2>回测工作台</h2>
          </div>
          <span className="section-note">点击行进入详情，右侧动作直接控制执行生命周期。</span>
        </div>

        {data.backtests.length ? (
          <>
            <div className="table-head replay-ledger-head">
              <span>策略 / 回测</span>
              <span>生命周期</span>
              <span>时间窗口</span>
              <span>结果</span>
              <span>最后活动</span>
            </div>
            <div className="record-list">
              {data.backtests.map((run) => {
              const owner = skillById.get(run.skill_id);
              const result = getRunReturnPct(run);
              const isPending = pendingKey?.startsWith(`${run.id}:`) ?? false;
              return (
                <article className="record-row dense-record" key={run.id}>
                  <div className="record-main">
                    <div className="record-cell">
                      <p className="record-title">{owner?.title ?? run.skill_id}</p>
                      <p className="record-subtitle">{run.id}</p>
                    </div>
                    <div className="record-cell">
                      <span className={`status-pill is-${toneForStatus(run.status)}`}>{describeStatus(run.status)}</span>
                      <p className="record-subtitle">
                        {run.pending_action ? `待执行 ${run.pending_action}` : `进度 ${getProgressLabel(run)}`}
                      </p>
                    </div>
                    <div className="record-cell">
                      <p className="record-subtitle">时间窗口</p>
                      <strong>{formatWindow(run.start_time_ms, run.end_time_ms)}</strong>
                    </div>
                    <div className="record-cell">
                      <p className="record-subtitle">结果</p>
                      <strong>{result == null ? '等待结果' : formatSignedPercent(result)}</strong>
                    </div>
                    <div className="record-cell">
                      <p className="record-subtitle">最后活动</p>
                      <strong>{formatTime(run.last_activity_at_ms ?? run.updated_at_ms)}</strong>
                    </div>
                  </div>
                  <div className="record-footer">
                    <div className="progress-shell">
                      <div className="progress-bar">
                        <span className="progress-fill" style={{ width: progressWidth(run) }} />
                      </div>
                      <span className="record-subtitle">{run.error_message ?? '结果汇总与时间线已保留。'}</span>
                    </div>
                    <div className="action-cluster">
                      <Link className="action-button" to={`/replays/${run.id}`}>
                        打开详情
                      </Link>
                      <LifecycleActions
                        actions={run.available_actions}
                        disabled={isPending}
                        onAction={(action) => void handleAction(run, action)}
                        pendingAction={run.pending_action}
                      />
                    </div>
                  </div>
                </article>
              );
              })}
            </div>
          </>
        ) : (
          <div className="empty-state">
            <strong>{loading ? '回测数据读取中...' : '还没有回测记录'}</strong>
            <p>去策略页选择策略并发起近 24 小时回测，这里会自动成为回测操作面板。</p>
          </div>
        )}
      </section>
    </div>
  );
}
