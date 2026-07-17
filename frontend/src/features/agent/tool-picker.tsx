import { Wrench } from "lucide-react";
import { useEffect, useState } from "react";

import { agentApi, type AgentToolCategory } from "../../api/agent";
import { Button } from "../../components/ui/button";
import { CenteredModal } from "../../components/ui/centered-modal";

export function ToolPicker({
  activeTools,
  disabled,
  onChange,
  onError,
}: {
  /** null means the server default is in effect and has not yet been loaded. */
  activeTools: string[] | null;
  disabled?: boolean;
  onChange: (tools: string[]) => void;
  onError: (message: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [categories, setCategories] = useState<AgentToolCategory[]>([]);
  const [defaults, setDefaults] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  useEffect(() => {
    if (!open || categories.length) return;
    const controller = new AbortController();
    void agentApi
      .getAvailableTools(controller.signal)
      .then((result) => {
        setCategories(result.categories);
        setDefaults(result.default_tools);
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted)
          onError(
            error instanceof Error ? error.message : "无法加载 Agent 工具。",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [categories.length, onError, open]);
  const selected = activeTools ?? defaults;
  const toggle = (name: string) =>
    onChange(
      selected.includes(name)
        ? selected.filter((item) => item !== name)
        : [...selected, name],
    );
  return (
    <>
      <Button
        aria-label="选择 Agent 工具"
        disabled={disabled}
        onClick={() => {
          setLoading(categories.length === 0);
          setOpen(true);
        }}
        variant="ghost"
      >
        <Wrench aria-hidden="true" size={18} />
      </Button>
      <CenteredModal
        onOpenChange={setOpen}
        open={open}
        title={`选择 Agent 工具（${selected.length}）`}
        size="lg"
      >
        <p className="text-sm text-[var(--text-muted)]">
          变更会重连当前会话，之后的请求仅可调用勾选工具；不会改写历史消息。
        </p>
        {loading ? <p>正在加载工具…</p> : null}
        <div className="agent-tool-categories">
          {categories.map((category) => (
            <fieldset key={category.id}>
              <legend>{category.display_name}</legend>
              <p>{category.description}</p>
              {category.tools.map((tool) => (
                <label key={tool.name}>
                  <input
                    checked={selected.includes(tool.name)}
                    onChange={() => toggle(tool.name)}
                    type="checkbox"
                  />
                  {tool.display_name}
                </label>
              ))}
            </fieldset>
          ))}
        </div>
        <div className="flex justify-end gap-2">
          <Button onClick={() => onChange(defaults)} variant="secondary">
            恢复默认
          </Button>
          <Button onClick={() => setOpen(false)} variant="primary">
            完成
          </Button>
        </div>
      </CenteredModal>
    </>
  );
}
