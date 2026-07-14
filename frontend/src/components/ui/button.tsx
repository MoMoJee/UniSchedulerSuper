import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";

import { cn } from "../../lib/cn";

const buttonVariants = cva(
  "inline-flex min-h-10 items-center justify-center rounded-lg px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        primary:
          "bg-[var(--accent)] text-white hover:bg-[var(--accent-strong)]",
        secondary:
          "bg-[var(--surface-muted)] text-[var(--text)] hover:bg-[var(--surface-hover)]",
        ghost: "text-[var(--text)] hover:bg-[var(--surface-hover)]",
        danger: "bg-[var(--danger)] text-white hover:brightness-95",
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
