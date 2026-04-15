import * as Dialog from '@radix-ui/react-dialog';
import { X } from 'lucide-react';

import StrategyComposer from './StrategyComposer';

type NewStrategyDrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
};

export default function NewStrategyDrawer({ open, onOpenChange }: NewStrategyDrawerProps) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="drawer-overlay" />
        <Dialog.Content className="drawer-content">
          <div className="drawer-header">
            <div>
              <Dialog.Title className="page-header-title">新建策略</Dialog.Title>
              <Dialog.Description className="page-header-desc">
                粘贴自然语言 Skill，系统会自动提取触发节奏、风控约束与工具需求。
              </Dialog.Description>
            </div>
            <Dialog.Close asChild>
              <button aria-label="关闭" className="drawer-close" type="button">
                <X size={18} />
              </button>
            </Dialog.Close>
          </div>
          <StrategyComposer
            description="创建后将生成不可编辑的策略版本，可立即用于回测与实时运行。"
            onCreated={() => onOpenChange(false)}
            title="策略 Skill 录入"
          />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
