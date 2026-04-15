import type { ExecutionAction } from '../types';

type LifecycleActionsProps = {
  actions: ExecutionAction[];
  disabled?: boolean;
  pendingAction?: string | null;
  onAction: (action: ExecutionAction) => void;
};

const ACTION_LABELS: Record<string, string> = {
  pause: '暂停',
  resume: '继续',
  stop: '停止',
  delete: '删除',
  trigger: '立即触发',
  create_backtest: '配置回测',
  create_live_task: '启动实时',
};

function actionTone(action: ExecutionAction): string {
  if (action === 'delete') return ' is-danger';
  if (action === 'stop') return ' is-warning';
  if (action === 'create_live_task' || action === 'resume' || action === 'trigger') return ' is-primary';
  return '';
}

export default function LifecycleActions({
  actions,
  disabled = false,
  pendingAction,
  onAction,
}: LifecycleActionsProps) {
  if (!actions.length) return null;

  return (
    <div className="action-row">
      {actions.map((action) => (
        <button
          className={`action-button${actionTone(action)}`}
          disabled={disabled}
          key={action}
          onClick={() => onAction(action)}
          type="button"
        >
          {pendingAction === action ? '处理中...' : ACTION_LABELS[action] ?? action}
        </button>
      ))}
    </div>
  );
}
