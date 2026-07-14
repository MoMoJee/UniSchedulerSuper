import { useQueryClient } from "@tanstack/react-query";
import { Bolt, LoaderCircle, Square, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { agentApi, type QuickActionTask } from "../../api/agent";
import { plannerKeys } from "../../api/queryKeys";
import { Button } from "../../components/ui/button";

export function QuickAction({
  onError,
}: {
  onError: (message: string) => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [task, setTask] = useState<QuickActionTask | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    [],
  );
  const poll = async (taskId: string) => {
    try {
      const next = await agentApi.getQuickAction(taskId);
      setTask(next);
      if (next.status === "pending" || next.status === "processing") {
        timer.current = window.setTimeout(() => void poll(taskId), 800);
      } else if (next.status === "success") {
        await queryClient.invalidateQueries({ queryKey: plannerKeys.all });
      }
    } catch (error) {
      onError(
        error instanceof Error ? error.message : "无法查询 Quick Action 状态。",
      );
    }
  };
  const submit = async () => {
    if (
      !text.trim() ||
      task?.status === "pending" ||
      task?.status === "processing"
    )
      return;
    try {
      const created = await agentApi.createQuickAction(text.trim());
      setTask(created);
      setText("");
      void poll(created.task_id);
    } catch (error) {
      onError(
        error instanceof Error ? error.message : "创建 Quick Action 失败。",
      );
    }
  };
  const cancel = async () => {
    if (!task || (task.status !== "pending" && task.status !== "processing"))
      return;
    try {
      await agentApi.cancelQuickAction(task.task_id);
      await poll(task.task_id);
    } catch (error) {
      onError(
        error instanceof Error ? error.message : "取消 Quick Action 失败。",
      );
    }
  };
  const running = task?.status === "pending" || task?.status === "processing";
  return (
    <div className="quick-action">
      <Button
        aria-expanded={open}
        aria-label="打开 Quick Action"
        variant="ghost"
        onClick={() => setOpen(!open)}
      >
        <Bolt aria-hidden="true" size={18} />
      </Button>
      {open ? (
        <div className="quick-action__panel">
          <div className="quick-action__heading">
            <strong>Quick Action</strong>
            <Button
              aria-label="关闭 Quick Action"
              variant="ghost"
              onClick={() => setOpen(false)}
            >
              <X aria-hidden="true" size={16} />
            </Button>
          </div>
          <label className="sr-only" htmlFor="quick-action-input">
            快捷指令
          </label>
          <input
            id="quick-action-input"
            disabled={running}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                void submit();
              }
            }}
            placeholder="例如：明天 9 点安排会议"
            value={text}
          />
          <div className="quick-action__actions">
            {running ? (
              <Button
                aria-label="取消 Quick Action"
                variant="danger"
                onClick={() => void cancel()}
              >
                <Square aria-hidden="true" size={15} />
                取消
              </Button>
            ) : (
              <Button
                disabled={!text.trim()}
                variant="primary"
                onClick={() => void submit()}
              >
                <Bolt aria-hidden="true" size={15} />
                执行
              </Button>
            )}
          </div>
          {task ? (
            <p className="quick-action__result" aria-live="polite">
              {running ? (
                <>
                  <LoaderCircle
                    aria-hidden="true"
                    className="animate-spin"
                    size={15}
                  />
                  正在执行…
                </>
              ) : (
                (task.result?.message ??
                (task.status === "success"
                  ? "快捷操作完成。"
                  : "快捷操作未完成。"))
              )}
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
