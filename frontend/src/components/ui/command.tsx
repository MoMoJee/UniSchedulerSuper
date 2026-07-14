import { Command as CommandPrimitive } from "cmdk";
import type { ComponentProps } from "react";

import { cn } from "../../lib/cn";

export const Command = CommandPrimitive;
export function CommandInput({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Input>) {
  return (
    <CommandPrimitive.Input
      className={cn("form-control", className)}
      {...props}
    />
  );
}
export const CommandList = CommandPrimitive.List;
export function CommandItem({
  className,
  ...props
}: ComponentProps<typeof CommandPrimitive.Item>) {
  return (
    <CommandPrimitive.Item className={cn("menu-item", className)} {...props} />
  );
}
