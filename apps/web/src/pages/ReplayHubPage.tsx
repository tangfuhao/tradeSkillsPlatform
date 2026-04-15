import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { toast } from 'sonner';

import AutoRefreshDot from '../components/AutoRefreshDot';
import ConfirmDialog from '../components/ConfirmDialog';
import LifecycleActions from '../components/LifecycleActions';
import LoadingSkeleton from '../components/LoadingSkeleton';
import PageHeader from '../components/PageHeader';
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

type StatusFilter = 'all' | 'active' | 'completed' | 'failed';

const FILTER_OPTIONS: { key: StatusFilter; label: string }[] = [
  { key: 'all', label: '全部' },
  { key: 'active', label: '运行中' },
  { key: 'completed', label: '已完成' },
  { key: 'failed', label: '失败/停止' },
];

function matchesFilter(run: BacktestRun, filter: StatusFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'active') return ['queued', 'running', 'paused', 'stopping'].includes(run.status);
  if (filter === 'completed') return run.status === 'completed';
  return run.status === 'failed' || run.status === 'stopped';
}

function progressWidth(run: BacktestRun): string {
  return `${Math.round((run.progress?.percent ?? 0) * 100)}%`;
}

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  tone: 'danger' | 'warning';
  onConfirm: () => void;
} | null;

export default function ReplayHubPage() {
  const [data, setData] = useState<ReplayData>({ backtests: [], skills: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pendingKey, setPendingKey] = useState<string | null>(null);
  const [filter, setFilter] = useState<StatusFilter>('all');
  const [confirm, setConfirm] = useState<ConfirmState>(null);
  const [lastRefreshMs, setLastRefreshMs] = useState<number | null>(null);
  const lastRefreshRef = useRef<number | null>(null);

  const load = useCallback(async () => {
    try {
      const [backtests, skills] = await Promise.all([listBacktests(), listSkills()]);
      setData({ backtests, skills });
      setError(null);
      const now = Date.now();
      lastRefreshRef.current = now;
      setLastRefreshMs(now);
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
  const filtered = useMemo(() => data.backtests.filter((run) => matchesFilter(run, filter)), [data.backtests, filter]);

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

  async function executeAction(run: BacktestRun, action: ExecutionAction) {
    const key = `${run.id}:${action}`;
    setPendingKey(key);
    try {
      if (action === 'delete') {
        await deleteBacktest(run.id);
        toast.success('回测已删除');
      } else {
        await controlBacktest(run.id, action);
        toast.success(`回测已${action === 'pause' ? '暂停' : action === 'resume' ? '继续' : '停止'}`);
      }
      await load();
    } catch (nextError) {
      toast.error(getErrorMessage(nextError));
    } finally {
      setPendingKey(null);
    }
  }

  function handleAction(run: BacktestRun, action: ExecutionAction) {
    if (action === 'delete') {
      setConfirm({
        title: '删除回测',
        description: '删除后将清除该回测的 traces、组合状态和执行细节，且无法恢复。',
        confirmLabel: '确认删除',
        tone: 'danger',
        onConfirm: () => {
          setConfirm(null);
          void executeAction(run, action);
        },
      });
      return;
    }
    if (action === 'stop') {
      setConfirm({
        title: '停止回测',
        description: '当前进度会保留，后续可以删除此回测。',
        confirmLabel: '确认停止',
        tone: 'warning',
        onConfirm: () => {
          setConfirm(null);
          void executeAction(run, action);
        },
      });
      return;
    }
    void executeAction(run, action);
  }

  return (
    <div className="page-stack">
      <PageHeader
        eyebrow="回测管理"
        title="回测工作台"
        description="查看、控制所有回测运行。点击行进入详情页。"
        actions={
          <>
            <AutoRefreshDot lastRefreshMs={lastRefreshMs} />
            <Link className="action-button is-primary" to="/strategies">
              发起新回测
            </Link>
          </>
        }
      />

      {loading && !data.backtests.length ? (
        <LoadingSkeleton variant="stat" />
      ) : (
        <section className="metric-grid">
          {stats.map((stat) => (
            <ProductStatTile detail={stat.detail} key={stat.label} label={stat.label} value={stat.value} />
          ))}
        </section>
      )}

      {error ? <div className="feedback-banner is-error">{error}</div> : null}

      <section className="surface">
        <div className="section-head">
          <div>
            <p className="section-eyebrow">回测记录</p>
            <h2>回测列表</h2>
          </div>
          <div className="filter-row">
            {FILTER_OPTIONS.map((opt) => (
              <button
                className={`filter-chip${filter === opt.key ? ' is-active' : ''}`}
                key={opt.key}
                onClick={() => setFilter(opt.key)}
                type="button"
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {loading && !data.backtests.length ? (
          <LoadingSkeleton rows={4} />
        ) : filtered.length ? (
          <>
            <div className="table-head replay-ledger-head">
              <span>策略 / 回测</span>
              <span>生命周期</span>
              <span>时间窗口</span>
              <span>结果</span>
              <span>最后活动</span>
            </div>
            <div className="record-list">
              {filtered.map((run) => {
              const owner = skillById.get(run.skill_id);
              const result = getRunReturnPct(run);
              const isPending = pendingKey?.startsWith(`${run.id}:`) ?? false;
              return (
                <article className="record-row dense-record" key={run.id}>
                  <div className="record-main">
                    <div className="record-cell">
                      <p className="record-title">
                        <span className={`status-dot is-${toneForStatus(run.status)}`} />
                        {owner?.title ?? run.skill_id}
                      </p>
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
                      <span className="record-subtitle">{run.error_message ?? ''}</span>
                    </div>
                    <div className="action-cluster">
                      <Link className="action-button" to={`/replays/${run.id}`}>
                        打开详情
                      </Link>
                      <LifecycleActions
                        actions={run.available_actions}
                        disabled={isPending}
                        onAction={(action) => handleAction(run, action)}
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
            <strong>
              {data.backtests.length ? '没有符合筛选条件的回测' : loading ? '回测数据读取中...' : '还没有回测记录'}
            </strong>
            <p>
              {data.backtests.length
                ? '调整筛选条件查看更多回测。'
                : '去策略页选择策略并配置回测窗口即可开始。'}
            </p>
          </div>
        )}
      </section>

      <ConfirmDialog
        open={confirm !== null}
        onOpenChange={(open) => { if (!open) setConfirm(null); }}
        title={confirm?.title ?? ''}
        description={confirm?.description ?? ''}
        confirmLabel={confirm?.confirmLabel ?? '确认'}
        tone={confirm?.tone ?? 'danger'}
        onConfirm={confirm?.onConfirm ?? (() => {})}
      />
    </div>
  );
}
