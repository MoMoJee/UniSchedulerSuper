import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const buttonVariants = cva(
  "inline-flex min-h-10 items-center justify-center gap-1.5 rounded-[0.68rem] border border-transparent px-3 text-sm font-semibold tracking-[-0.01em] shadow-sm transition-[transform,background-color,border-color,color,box-shadow] duration-150 ease-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[var(--surface)] active:scale-[0.97] disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--accent)] text-white shadow-[0_6px_16px_color-mix(in_srgb,var(--accent)_22%,transparent)] hover:-translate-y-px hover:bg-[var(--accent-strong)] hover:shadow-[0_8px_20px_color-mix(in_srgb,var(--accent)_26%,transparent)]",
        secondary:
          "border-[var(--border)] bg-[color-mix(in_srgb,var(--surface)_92%,transparent)] text-[var(--text)] hover:-translate-y-px hover:border-[var(--border-strong)] hover:bg-[var(--surface)] hover:shadow-md",
        ghost: "shadow-none text-[var(--text)] hover:bg-[var(--surface-hover)]",
        danger:
          "bg-[var(--danger)] text-white shadow-[0_6px_16px_color-mix(in_srgb,var(--danger)_20%,transparent)] hover:-translate-y-px hover:brightness-95",
      },
    },
    defaultVariants: { variant: "secondary" },
  },
);

export interface ButtonProps
  extends
    ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  function Button({ className, variant, type = "button", ...props }, ref) {
    return (
      <button
        className={cn(buttonVariants({ variant }), className)}
        ref={ref}
        type={type}
        {...props}
      />
    );
  },
);
