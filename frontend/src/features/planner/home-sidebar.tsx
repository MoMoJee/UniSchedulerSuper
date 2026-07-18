import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Check, Filter, LayoutGrid, List, Plus } from "lucide-react";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import {
  mapPlannerOccurrence,
  type PlannerOccurrence,
} from "../../api/mappers";
import { plannerApi } from "../../api/planner";
import { plannerKeys } from "../../api/queryKeys";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { CenteredModal } from "../../components/ui/centered-modal";
import { Input, Textarea } from "../../components/ui/form";
import { Popover } from "../../components/ui/overlays";
import { ReminderPanel } from "./reminder-panel";

type TodoItem = {
  id: string;
  version: number;
  title: string;
  description: string;
  status: string;
  due: string | null;
  importance: string;
  urgency: string;
  groupId: string | null;
};

const QUADRANTS = [
  { key: "urgent", label: "重要且紧急", hint: "立即处理" },
  { key: "plan", label: "重要不紧急", hint: "安排计划" },
  { key: "delegate", label: "紧急不重要", hint: "尽快处理" },
  { key: "later", label: "其他待办", hint: "稍后处理" },
] as const;

function mapTodo(value: Record<string, unknown>): TodoItem | null {
  return typeof value.todo_id === "string" &&
    typeof value.title === "string" &&
    typeof value.version === "number"
    ? {
        id: value.todo_id,
        version: value.version,
        title: value.title,
        description:
          typeof value.description === "string" ? value.description : "",
        status: typeof value.status === "string" ? value.status : "pending",
        due: typeof value.due === "string" ? value.due : null,
        importance:
          typeof value.importance === "string" ? value.importance : "",
        urgency: typeof value.urgency === "string" ? value.urgency : "",
        groupId: typeof value.group_id === "string" ? value.group_id : null,
      }
    : null;
}

function quadrant(todo: TodoItem) {
  if (todo.importance === "high" && todo.urgency === "high") return "urgent";
  if (todo.importance === "high") return "plan";
  if (todo.urgency === "high") return "delegate";
  return "later";
}

function range(days: number) {
  const from = new Date();
  from.setHours(0, 0, 0, 0);
  const to = new Date(from);
  to.setDate(to.getDate() + days);
  return { from: from.toISOString(), to: to.toISOString() };
}

function TodoModal({
  item,
  open,
  onClose,
}: {
  item: TodoItem | null;
  open: boolean;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(item?.title ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [due, setDue] = useState(item?.due?.slice(0, 16) ?? "");
  const [importance, setImportance] = useState(item?.importance ?? "");
  const [urgency, setUrgency] = useState(item?.urgency ?? "");
  const client = useQueryClient();
  const save = useMutation({
    mutationFn: () => {
      if (!title.trim()) throw new Error("待办标题不能为空。");
      const body = {
        title: title.trim(),
        description,
        importance,
        urgency,
        due: due ? new Date(due).toISOString() : null,
        tzid: "Asia/Shanghai",
      };
      return item
        ? plannerApi.patchTodo(item.id, body, item.version)
        : plannerApi.createTodo({ ...body, status: "pending" });
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: plannerKeys.all });
      onClose();
    },
  });
  return (
    <CenteredModal
      open={open}
      onOpenChange={(next) => !next && onClose()}
      title={item ? "编辑待办" : "创建待办"}
      size="md"
    >
      <form
        className="todo-modal"
        onSubmit={(event) => {
          event.preventDefault();
          save.mutate();
        }}
      >
        <label>
          标题
          <Input
            autoFocus
            value={title}
            onChange={(event) => setTitle(event.target.value)}
          />
        </label>
        <label>
          描述
          <Textarea
            value={description}
            onChange={(event) => setDescription(event.target.value)}
          />
        </label>
        <label>
          截止时间
          <Input
            type="datetime-local"
            value={due}
            onChange={(event) => setDue(event.target.value)}
          />
        </label>
        <div className="todo-modal__pair">
          <label>
            重要性
            <select
              value={importance}
              onChange={(event) => setImportance(event.target.value)}
            >
              <option value="">未设置</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </label>
          <label>
            紧急性
            <select
              value={urgency}
              onChange={(event) => setUrgency(event.target.value)}
            >
              <option value="">未设置</option>
              <option value="low">低</option>
              <option value="medium">中</option>
              <option value="high">高</option>
            </select>
          </label>
        </div>
        {save.error ? <ApiErrorNotice error={save.error} /> : null}
        <div className="todo-modal__actions">
          <Button onClick={onClose}>取消</Button>
          <Button disabled={save.isPending} type="submit" variant="primary">
            {save.isPending ? "保存中…" : "保存"}
          </Button>
        </div>
      </form>
    </CenteredModal>
  );
}

export function HomeSidebar({ username }: { username: string }) {
  const [params, setParams] = useSearchParams();
  const client = useQueryClient();
  const [view, setView] = useState<"quadrant" | "list">(() =>
    localStorage.getItem("unischedulersuper-todo-view") === "list"
      ? "list"
      : "quadrant",
  );
  const [todoStatus, setTodoStatus] = useState("pending");
  const [importance, setImportance] = useState("");
  const [todoModal, setTodoModal] = useState<TodoItem | "new" | null>(null);
  const [reminderDays, setReminderDays] = useState(7);
  const [repeatOnly, setRepeatOnly] = useState(false);
  const [reminderModal, setReminderModal] = useState<
    PlannerOccurrence | "new" | null
  >(null);
  const windowRange = useMemo(() => range(reminderDays), [reminderDays]);
  const todos = useQuery({
    queryKey: [...plannerKeys.all, "home-todos", username, todoStatus],
    queryFn: async ({ signal }) =>
      (
        await plannerApi.listTodos({ status: todoStatus }, signal)
      ).todos?.flatMap((value) => {
        const item = mapTodo(value);
        return item ? [item] : [];
      }) ?? [],
  });
  const reminders = useQuery({
    queryKey: [
      ...plannerKeys.all,
      "home-reminders",
      username,
      windowRange.from,
      windowRange.to,
    ],
    queryFn: async ({ signal }) =>
      (
        await plannerApi.listReminders(windowRange.from, windowRange.to, signal)
      ).occurrences?.map(mapPlannerOccurrence) ?? [],
  });
  const refresh = () => client.invalidateQueries({ queryKey: plannerKeys.all });
  const patchTodo = useMutation({
    mutationFn: ({ item, status }: { item: TodoItem; status: string }) =>
      plannerApi.patchTodo(item.id, { status }, item.version),
    onSuccess: refresh,
  });
  const deleteTodo = useMutation({
    mutationFn: (item: TodoItem) =>
      plannerApi.deleteTodo(item.id, item.version),
    onSuccess: refresh,
  });
  const convertTodo = useMutation({
    mutationFn: (item: TodoItem) => {
      const start = new Date();
      const end = new Date(start.getTime() + 3_600_000);
      return plannerApi.convertTodo(
        item.id,
        {
          title: item.title,
          description: item.description,
          start: start.toISOString(),
          end: end.toISOString(),
          tzid: "Asia/Shanghai",
        },
        item.version,
      );
    },
    onSuccess: refresh,
  });
  const reminderAction = useMutation({
    mutationFn: ({
      item,
      action,
    }: {
      item: PlannerOccurrence;
      action: "complete" | "dismiss" | "snooze";
    }) => {
      if (!item.occurrenceRef) throw new Error("提醒缺少 occurrence_ref。");
      return plannerApi.actOnReminderOccurrence(
        action,
        {
          entity_id: item.occurrenceRef.entityId,
          series_id: item.occurrenceRef.seriesId,
          recurrence_id: item.occurrenceRef.recurrenceId,
          source_version: item.occurrenceRef.sourceVersion,
        },
        item.occurrenceRef.sourceVersion,
        action === "snooze"
          ? new Date(Date.now() + 3_600_000).toISOString()
          : undefined,
      );
    },
    onSuccess: refresh,
  });
  const todoItems = (todos.data ?? []).filter(
    (item) => !importance || item.importance === importance,
  );
  const reminderItems = (reminders.data ?? []).filter(
    (item) => !repeatOnly || Boolean(item.occurrenceRef?.seriesId),
  );
  const error =
    todos.error ??
    reminders.error ??
    patchTodo.error ??
    deleteTodo.error ??
    convertTodo.error ??
    reminderAction.error;
  const urlTodo =
    params.get("dialog") === "todo"
      ? (todos.data?.find((item) => item.id === params.get("entity")) ?? null)
      : null;
  const effectiveTodoModal = todoModal ?? urlTodo;
  const closeTodoModal = () => {
    setTodoModal(null);
    if (params.get("dialog") === "todo") {
      const copy = new URLSearchParams(params);
      copy.delete("dialog");
      copy.delete("entity");
      setParams(copy, { replace: true });
    }
  };

  const TodoCard = ({ item }: { item: TodoItem }) => (
    <li className={`home-todo-card home-todo-card--${quadrant(item)}`}>
      <button
        aria-label={
          item.status === "completed"
            ? `恢复 ${item.title}`
            : `完成 ${item.title}`
        }
        className="home-todo-card__check"
        onClick={() =>
          patchTodo.mutate({
            item,
            status: item.status === "completed" ? "pending" : "completed",
          })
        }
        type="button"
      >
        <Check size={13} />
      </button>
      <button
        className="home-todo-card__body"
        onClick={() => setTodoModal(item)}
        type="button"
      >
        <strong>{item.title}</strong>
        {item.description ? <span>{item.description}</span> : null}
        {item.due ? (
          <small>
            {new Date(item.due).toLocaleString("zh-CN", {
              month: "numeric",
              day: "numeric",
              hour: "2-digit",
              minute: "2-digit",
            })}
          </small>
        ) : null}
      </button>
      <details>
        <summary aria-label="待办操作">•••</summary>
        <div>
          <button onClick={() => setTodoModal(item)}>编辑</button>
          <button onClick={() => convertTodo.mutate(item)}>转日程</button>
          <button onClick={() => deleteTodo.mutate(item)}>删除</button>
        </div>
      </details>
    </li>
  );

  return (
    <aside aria-label="待办与提醒" className="home-sidebar">
      <section className="home-sidebar__section home-sidebar__section--todos">
        <header>
          <div>
            <Check aria-hidden="true" size={17} />
            <strong>待办事项</strong>
          </div>
          <div>
            <Button
              aria-label="列表视图"
              onClick={() => {
                setView("list");
                localStorage.setItem("unischedulersuper-todo-view", "list");
              }}
              variant={view === "list" ? "primary" : "ghost"}
            >
              <List size={14} />
            </Button>
            <Button
              aria-label="四象限视图"
              onClick={() => {
                setView("quadrant");
                localStorage.setItem("unischedulersuper-todo-view", "quadrant");
              }}
              variant={view === "quadrant" ? "primary" : "ghost"}
            >
              <LayoutGrid size={14} />
            </Button>
            <Popover
              trigger={
                <Button aria-label="筛选待办" variant="ghost">
                  <Filter size={14} />
                </Button>
              }
            >
              <div className="sidebar-filter">
                <label>
                  状态
                  <select
                    value={todoStatus}
                    onChange={(e) => setTodoStatus(e.target.value)}
                  >
                    <option value="">全部</option>
                    <option value="pending">未完成</option>
                    <option value="completed">已完成</option>
                  </select>
                </label>
                <label>
                  重要性
                  <select
                    value={importance}
                    onChange={(e) => setImportance(e.target.value)}
                  >
                    <option value="">全部</option>
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                  </select>
                </label>
                <Button
                  onClick={() => {
                    setTodoStatus("pending");
                    setImportance("");
                  }}
                  variant="ghost"
                >
                  重置
                </Button>
              </div>
            </Popover>
            <Button
              aria-label="创建待办"
              onClick={() => setTodoModal("new")}
              variant="ghost"
            >
              <Plus size={15} />
            </Button>
          </div>
        </header>
        {error ? <ApiErrorNotice error={error} /> : null}
        {todos.isLoading ? (
          <p className="home-sidebar__state">正在加载待办…</p>
        ) : view === "quadrant" ? (
          <div className="home-sidebar__quadrants">
            {QUADRANTS.map((entry) => {
              const items = todoItems.filter(
                (item) => quadrant(item) === entry.key,
              );
              return (
                <section key={entry.key}>
                  <h2>
                    {entry.label}
                    <small>{entry.hint}</small>
                  </h2>
                  <ul>
                    {items.map((item) => (
                      <TodoCard item={item} key={item.id} />
                    ))}
                    {!items.length ? (
                      <li className="home-sidebar__empty">暂无待办</li>
                    ) : null}
                  </ul>
                </section>
              );
            })}
          </div>
        ) : (
          <ul className="home-sidebar__todo-list">
            {todoItems.map((item) => (
              <TodoCard item={item} key={item.id} />
            ))}
            {!todoItems.length ? (
              <li className="home-sidebar__empty">暂无待办</li>
            ) : null}
          </ul>
        )}
      </section>
      <section className="home-sidebar__section home-sidebar__section--reminders">
        <header>
          <div>
            <BellRing aria-hidden="true" size={17} />
            <strong>提醒</strong>
          </div>
          <div>
            <Popover
              trigger={
                <Button aria-label="筛选提醒" variant="ghost">
                  <Filter size={14} />
                </Button>
              }
            >
              <div className="sidebar-filter">
                <label>
                  时间范围
                  <select
                    value={reminderDays}
                    onChange={(e) => setReminderDays(Number(e.target.value))}
                  >
                    <option value={1}>今天</option>
                    <option value={7}>未来 7 天</option>
                    <option value={30}>未来 30 天</option>
                  </select>
                </label>
                <label>
                  <input
                    checked={repeatOnly}
                    onChange={(e) => setRepeatOnly(e.target.checked)}
                    type="checkbox"
                  />{" "}
                  仅重复提醒
                </label>
              </div>
            </Popover>
            <Button
              aria-label="创建提醒"
              onClick={() => setReminderModal("new")}
              variant="ghost"
            >
              <Plus size={15} />
            </Button>
          </div>
        </header>
        {reminders.isLoading ? (
          <p className="home-sidebar__state">正在加载提醒…</p>
        ) : (
          <ul className="home-sidebar__reminders">
            {reminderItems.map((item) => (
              <li key={item.id}>
                <button
                  className="home-reminder-card"
                  onClick={() => setReminderModal(item)}
                  type="button"
                >
                  <span className="home-reminder-card__icon">
                    <BellRing size={13} />
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <small>
                      {new Date(item.start).toLocaleString("zh-CN", {
                        month: "numeric",
                        day: "numeric",
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                      {item.occurrenceRef?.seriesId ? " · 重复" : " · 单次"}
                    </small>
                  </span>
                </button>
                <details>
                  <summary>•••</summary>
                  <div>
                    <button
                      onClick={() =>
                        reminderAction.mutate({ item, action: "complete" })
                      }
                    >
                      完成
                    </button>
                    <button
                      onClick={() =>
                        reminderAction.mutate({ item, action: "snooze" })
                      }
                    >
                      延后1小时
                    </button>
                    <button
                      onClick={() =>
                        reminderAction.mutate({ item, action: "dismiss" })
                      }
                    >
                      忽略
                    </button>
                  </div>
                </details>
              </li>
            ))}
            {!reminderItems.length ? (
              <li className="home-sidebar__empty">当前范围没有提醒</li>
            ) : null}
          </ul>
        )}
      </section>
      <TodoModal
        item={effectiveTodoModal === "new" ? null : effectiveTodoModal}
        key={
          effectiveTodoModal === "new"
            ? "todo-new"
            : `todo-${effectiveTodoModal?.id ?? "closed"}`
        }
        onClose={closeTodoModal}
        open={effectiveTodoModal !== null}
      />
      <ReminderPanel
        item={reminderModal === "new" ? null : reminderModal}
        key={
          reminderModal === "new"
            ? "reminder-new"
            : `reminder-${reminderModal?.id ?? "closed"}`
        }
        onClose={() => setReminderModal(null)}
        open={reminderModal !== null}
      />
    </aside>
  );
}
