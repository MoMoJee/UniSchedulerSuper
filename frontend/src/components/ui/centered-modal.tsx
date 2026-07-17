import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";

import { cn } from "../../lib/cn";

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
        <Dialog.Overlay className="centered-modal__overlay" />
        <Dialog.Content
          aria-describedby={description ? undefined : undefined}
          className={cn("centered-modal", `centered-modal--${size}`)}
        >
          <header className="centered-modal__header">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              {description ? (
                <Dialog.Description>{description}</Dialog.Description>
              ) : null}
            </div>
            <Dialog.Close aria-label="关闭" className="centered-modal__close">
              <X aria-hidden="true" size={19} />
            </Dialog.Close>
          </header>
          <div className="centered-modal__body">{children}</div>
          {footer ? (
            <footer className="centered-modal__footer">{footer}</footer>
          ) : null}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
