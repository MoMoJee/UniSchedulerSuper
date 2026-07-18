import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import { cn } from "../../lib/cn";
import styles from "./centered-modal.module.css";

export function CenteredModal({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  size = "md",
  restoreFocusRef,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: "sm" | "md" | "lg" | "xl";
  restoreFocusRef?: RefObject<HTMLElement | null>;
}) {
  const wasOpen = useRef(open);
  useEffect(() => {
    if (wasOpen.current && !open) restoreFocusRef?.current?.focus();
    wasOpen.current = open;
  }, [open, restoreFocusRef]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className={styles.overlay} />
        <Dialog.Content
          className={cn(styles.content, styles[size])}
          data-ui="centered-modal"
        >
          <header className={styles.header}>
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {description ? (
                <Dialog.Description>{description}</Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close aria-label="关闭" className={styles.close}>
              <X aria-hidden="true" size={19} />
            </Dialog.Close>
          </header>
          <div className={styles.body}>{children}</div>
          {footer ? <footer className={styles.footer}>{footer}</footer> : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
