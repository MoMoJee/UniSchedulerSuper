import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "../../lib/cn";

export const Tabs = TabsPrimitive.Root;
export const TabsContent = TabsPrimitive.Content;

export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return (
    <TabsPrimitive.List
      className={cn(
        "inline-flex rounded-lg bg-[var(--surface-muted)] p-1",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  ...props
}: TabsPrimitive.TabsTriggerProps) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "rounded-md px-3 py-1.5 text-sm text-[var(--text-muted)] outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] data-[state=active]:bg-[var(--surface)] data-[state=active]:text-[var(--text)]",
        className,
      )}
      {...props}
    />
  );
}
