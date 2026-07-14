import * as SelectPrimitive from "@radix-ui/react-select";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import type { ComponentProps } from "react";

import { cn } from "../../lib/cn";

export function Input({ className, ...props }: ComponentProps<"input">) {
  return <input className={cn("form-control", className)} {...props} />;
}

export function Textarea({ className, ...props }: ComponentProps<"textarea">) {
  return (
    <textarea className={cn("form-control min-h-24", className)} {...props} />
  );
}

export function Checkbox({ className, ...props }: ComponentProps<"input">) {
  return (
    <input
      className={cn("h-4 w-4 accent-[var(--accent)]", className)}
      type="checkbox"
      {...props}
    />
  );
}

export function Switch({
  checked,
  onCheckedChange,
  label,
}: {
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
  label: string;
}) {
  return (
    <SwitchPrimitive.Root
      aria-label={label}
      checked={checked}
      className="switch-root"
      onCheckedChange={onCheckedChange}
    >
      <SwitchPrimitive.Thumb className="switch-thumb" />
    </SwitchPrimitive.Root>
  );
}

export function Select({
  value,
  onValueChange,
  placeholder,
  options,
}: {
  value?: string;
  onValueChange: (value: string) => void;
  placeholder: string;
  options: Array<{ value: string; label: string; disabled?: boolean }>;
}) {
  return (
    <SelectPrimitive.Root onValueChange={onValueChange} value={value}>
      <SelectPrimitive.Trigger
        aria-label={placeholder}
        className="form-control flex items-center justify-between"
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon aria-hidden="true">⌄</SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content className="menu-content" position="popper">
          <SelectPrimitive.Viewport>
            {options.map((option) => (
              <SelectPrimitive.Item
                className="menu-item"
                disabled={option.disabled}
                key={option.value}
                value={option.value}
              >
                <SelectPrimitive.ItemText>
                  {option.label}
                </SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  );
}
