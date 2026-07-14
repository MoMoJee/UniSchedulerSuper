import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { useEffect, useRef, type RefObject } from "react";

import { Button } from "./button";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel?: string;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  /** Required when a controlled dialog is opened from a button outside Radix Trigger. */
  restoreFocusRef?: RefObject<HTMLElement | null>;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "确认",
  onOpenChange,
  onConfirm,
  restoreFocusRef,
}: ConfirmDialogProps) {
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) restoreFocusRef?.current?.focus();
    wasOpen.current = open;
  }, [open, restoreFocusRef]);

  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="dialog-overlay" />
        <AlertDialog.Content className="dialog-content">
          <AlertDialog.Title className="text-lg font-semibold">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-[var(--text-muted)]">
            {description}
          </AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <Button>取消</Button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <Button variant="danger" onClick={onConfirm}>
                {confirmLabel}
              </Button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
