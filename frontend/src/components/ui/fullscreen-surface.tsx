import { ArrowLeft, X } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "./button";

export function FullscreenSurface({
  open,
  title,
  children,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  if (!open) return null;
  return (
    <section
      aria-label={title}
      className="fullscreen-surface"
      role="dialog"
      aria-modal="true"
    >
      <div className="fullscreen-surface__header">
        <Button onClick={onClose} variant="ghost">
          <ArrowLeft aria-hidden="true" size={18} /> 返回工作台
        </Button>
        <strong>{title}</strong>
        <Button aria-label="关闭" onClick={onClose} variant="ghost">
          <X aria-hidden="true" size={18} />
        </Button>
      </div>
      <div className="fullscreen-surface__body">{children}</div>
    </section>
  );
}
