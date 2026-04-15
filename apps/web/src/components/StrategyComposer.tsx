import { useState, type FormEvent } from 'react';
import { toast } from 'sonner';

import { createSkill } from '../api';
import { getErrorMessage } from '../lib/formatting';
import type { Skill } from '../types';

type StrategyComposerProps = {
  title: string;
  description: string;
  submitLabel?: string;
  onCreated?: (skill: Skill) => void;
  className?: string;
  variant?: 'default' | 'desk';
};

const SAMPLE_PLACEHOLDER = `# Breakout Rotation Skill

## Execution Cadence
Every 15 minutes.

## AI Reasoning
Scan strong perpetual swap trends and only act when follow-through still has room.

## Risk Control
- Max position size: 8%
- Max daily drawdown: 6%
- Max concurrent positions: 2
- Stop loss: 2%`;

export default function StrategyComposer({
  title,
  description,
  submitLabel = '创建策略',
  onCreated,
  className,
  variant = 'default',
}: StrategyComposerProps) {
  const [strategyTitle, setStrategyTitle] = useState('');
  const [strategyText, setStrategyText] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const normalizedTitle = strategyTitle.trim();
  const normalizedSkillLength = strategyText.trim().length;
  const canSubmit = normalizedSkillLength >= 20;

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);

    try {
      const created = await createSkill({
        title: strategyTitle.trim() || undefined,
        skill_text: strategyText,
      });
      setStrategyTitle('');
      setStrategyText('');
      toast.success(`策略已创建：${created.title}`);
      onCreated?.(created);
    } catch (nextError) {
      toast.error(`创建失败：${getErrorMessage(nextError)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className={`surface composer-surface${variant === 'desk' ? ' is-desk' : ''}${className ? ` ${className}` : ''}`}>
      {variant === 'desk' ? (
        <div className="composer-ledger">
          <div className="composer-ledger-cell">
            <span>录入模式</span>
            <strong>策略录入台</strong>
          </div>
          <div className="composer-ledger-cell">
            <span>版本策略</span>
            <strong>不可变策略</strong>
          </div>
          <div className="composer-ledger-cell">
            <span>绑定关系</span>
            <strong>1 策略 → N 回测 + 1 实时</strong>
          </div>
        </div>
      ) : null}
      <div className="section-head">
        <div>
          <p className="section-eyebrow">创建策略</p>
          <h2>{title}</h2>
        </div>
        <p className="section-note">{description}</p>
      </div>
      <form className="composer-form" onSubmit={handleSubmit}>
        <label className="field-block">
          <span>策略标题（可选）</span>
          <input
            className="field-input"
            disabled={submitting}
            maxLength={120}
            onChange={(event) => setStrategyTitle(event.target.value)}
            placeholder="例如：Trend Pullback Rotation"
            value={strategyTitle}
          />
        </label>
        <label className="field-block field-block-wide">
          <span>策略 Skill</span>
          <textarea
            className="field-textarea"
            disabled={submitting}
            minLength={20}
            onChange={(event) => setStrategyText(event.target.value)}
            placeholder={SAMPLE_PLACEHOLDER}
            rows={variant === 'desk' ? 14 : 10}
            value={strategyText}
          />
        </label>
        <div className="composer-telemetry">
          <div className="composer-telemetry-item">
            <span>标题</span>
            <strong>{normalizedTitle || '自动生成'}</strong>
          </div>
          <div className="composer-telemetry-item">
            <span>字数</span>
            <strong>{normalizedSkillLength}</strong>
          </div>
          <div className="composer-telemetry-item">
            <span>状态</span>
            <strong>{submitting ? '提交中' : canSubmit ? '就绪' : '等待输入'}</strong>
          </div>
        </div>
        <div className="composer-footer">
          <p className="muted-copy">策略一旦创建即视为不可编辑版本，后续调整请创建新策略。</p>
          <button className="action-button is-primary" disabled={submitting || !canSubmit} type="submit">
            {submitting ? '创建中...' : submitLabel}
          </button>
        </div>
      </form>
    </section>
  );
}
