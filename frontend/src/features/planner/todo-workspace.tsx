import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LayoutGrid, List, Plus } from "lucide-react";
import { useState } from "react";

import { plannerApi } from "../../api/planner";
import { plannerKeys } from "../../api/queryKeys";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { Input, Select, Textarea } from "../../components/ui/form";
import { Badge, Skeleton } from "../../components/ui/status";

interface TodoItem {
  id: string;
  version: number;
  title: string;
  description: string;
  status: string;
  due: string | null;
  importance: string;
  urgency: string;
}

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
      }
    : null;
}

function todoPayload(item: TodoItem) {
  if (!item.title.trim()) throw new Error("标题不能为空。");
  return {
    title: item.title.trim(),
    description: item.description,
    importance: item.importance,
    urgency: item.urgency,
    ...(item.due ? { due: item.due, tzid: "Asia/Shanghai" } : { due: null }),
  };
}

export function TodoWorkspace({ username }: { username: string }) {
  const [view, setView] = useState<"quadrant" | "list">(() =>
    window.localStorage.getItem("unischedulersuper-todo-view") === "list"
      ? "list"
      : "quadrant",
  );
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [due, setDue] = useState("");
  const [importance, setImportance] = useState("");
  const [urgency, setUrgency] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [editing, setEditing] = useState<TodoItem | null>(null);
  const client = useQueryClient();
  const todos = useQuery({
    queryKey: [...plannerKeys.all, "todos", username, statusFilter],
    queryFn: async ({ signal }) =>
      (
        await plannerApi.listTodos({ status: statusFilter }, signal)
      ).todos?.flatMap((value) => {
        const item = mapTodo(value);
        return item ? [item] : [];
      }) ?? [],
  });
  const refresh = () => client.invalidateQueries({ queryKey: plannerKeys.all });
  const create = useMutation({
    mutationFn: () => {
      if (!title.trim()) throw new Error("标题不能为空。");
      return plannerApi.createTodo({
        title: title.trim(),
        description,
        status: "pending",
        ...(due
          ? { due: new Date(due).toISOString(), tzid: "Asia/Shanghai" }
          : {}),
        ...(importance ? { importance } : {}),
        ...(urgency ? { urgency } : {}),
      });
    },
    onSuccess: async () => {
      setTitle("");
      setDescription("");
      setDue("");
      setImportance("");
      setUrgency("");
      await refresh();
    },
  });
  const patch = useMutation({
    mutationFn: ({ item, status }: { item: TodoItem; status: string }) =>
      plannerApi.patchTodo(item.id, { status }, item.version),
    onSuccess: refresh,
  });
  const edit = useMutation({
    mutationFn: (item: TodoItem) =>
      plannerApi.patchTodo(item.id, todoPayload(item), item.version),
    onSuccess: async () => {
      setEditing(null);
      await refresh();
    },
  });
  const remove = useMutation({
    mutationFn: (item: TodoItem) =>
      plannerApi.deleteTodo(item.id, item.version),
    onSuccess: refresh,
  });
  const convert = useMutation({
    mutationFn: (item: TodoItem) => {
      const start = new Date();
      const end = new Date(start.getTime() + 60 * 60 * 1000);
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
  const error =
    create.error ??
    todos.error ??
    patch.error ??
    edit.error ??
    remove.error ??
    convert.error;
  return (
    <section className="planner-workspace">
      <div className="planner-toolbar">
        <div>
          <span className="workspace-eyebrow">待办工作区</span>
          <h1 className="mt-1 text-2xl font-semibold">四象限待办</h1>
        </div>
        <div className="flex gap-2">
          <Button
            aria-pressed={view === "quadrant"}
            onClick={() => {
              setView("quadrant");
              window.localStorage.setItem(
                "unischedulersuper-todo-view",
                "quadrant",
              );
            }}
            variant="ghost"
          >
            <LayoutGrid size={16} /> 四象限
          </Button>
          <Button
            aria-pressed={view === "list"}
            onClick={() => {
              setView("list");
              window.localStorage.setItem(
                "unischedulersuper-todo-view",
                "list",
              );
            }}
            variant="ghost"
          >
            <List size={16} /> 列表
          </Button>
        </div>
      </div>
      <form
        className="planner-filters"
        onSubmit={(event) => {
          event.preventDefault();
          create.mutate();
        }}
      >
        <Input
          onChange={(event) => setTitle(event.target.value)}
          placeholder="新增待办"
          value={title}
        />
        <Textarea
          onChange={(event) => setDescription(event.target.value)}
          placeholder="描述（可选）"
          value={description}
        />
        <Input
          aria-label="截止时间"
          onChange={(event) => setDue(event.target.value)}
          type="datetime-local"
          value={due}
        />
        <Select
          onValueChange={setImportance}
          options={[
            { value: "", label: "默认重要性" },
            { value: "low", label: "低重要性" },
            { value: "medium", label: "中重要性" },
            { value: "high", label: "高重要性" },
          ]}
          placeholder="重要性"
          value={importance}
        />
        <Select
          onValueChange={setUrgency}
          options={[
            { value: "", label: "默认紧急度" },
            { value: "low", label: "低紧急度" },
            { value: "medium", label: "中紧急度" },
            { value: "high", label: "高紧急度" },
          ]}
          placeholder="紧急度"
          value={urgency}
        />
        <Button disabled={create.isPending} type="submit" variant="primary">
          <Plus size={16} /> 新增待办
        </Button>
      </form>
      <div className="planner-filters mt-3">
        <Select
          onValueChange={setStatusFilter}
          options={[
            { value: "", label: "全部状态" },
            { value: "pending", label: "未完成" },
            { value: "completed", label: "已完成" },
          ]}
          placeholder="状态筛选"
          value={statusFilter}
        />
        <span className="text-sm text-[var(--text-muted)]">
          列表按服务端截止时间排序；V2
          没有持久化手动排序字段，因此不提供会回退的拖拽排序。
        </span>
      </div>
      {error ? (
        <ApiErrorNotice error={error} onRetry={() => todos.refetch()} />
      ) : null}
      {todos.isLoading ? (
        <Skeleton className="h-60" />
      ) : (
        <div className={view === "quadrant" ? "todo-quadrants" : "todo-list"}>
          {view === "quadrant" ? (
            [
              {
                key: "high-high",
                label: "重要且紧急",
                description: "立即处理",
                filter: (item: TodoItem) =>
                  item.importance === "high" && item.urgency === "high",
              },
              {
                key: "high-rest",
                label: "重要不紧急",
                description: "安排计划",
                filter: (item: TodoItem) =>
                  item.importance === "high" && item.urgency !== "high",
              },
              {
                key: "rest-high",
                label: "紧急不重要",
                description: "尽快处理",
                filter: (item: TodoItem) =>
                  item.importance !== "high" && item.urgency === "high",
              },
              {
                key: "rest-rest",
                label: "其他待办",
                description: "稍后处理",
                filter: (item: TodoItem) =>
                  item.importance !== "high" && item.urgency !== "high",
              },
            ].map((quadrant) => (
              <section className="todo-quadrant" key={quadrant.key}>
                <header>
                  <strong>{quadrant.label}</strong>
                  <small>{quadrant.description}</small>
                </header>
                <ul>
                  {todos.data?.filter(quadrant.filter).map((item) => (
                    <li className="todo-card" key={item.id}>
                      <div className="flex-1">
                        {editing?.id === item.id ? (
                          <div className="space-y-2">
                            <Input
                              aria-label="编辑待办标题"
                              onChange={(event) =>
                                setEditing({
                                  ...editing,
                                  title: event.target.value,
                                })
                              }
                              value={editing.title}
                            />
                            <Textarea
                              aria-label="编辑待办描述"
                              onChange={(event) =>
                                setEditing({
                                  ...editing,
                                  description: event.target.value,
                                })
                              }
                              value={editing.description}
                            />
                            <Input
                              aria-label="编辑截止时间"
                              onChange={(event) =>
                                setEditing({
                                  ...editing,
                                  due: event.target.value
                                    ? new Date(event.target.value).toISOString()
                                    : null,
                                })
                              }
                              type="datetime-local"
                              value={editing.due?.slice(0, 16) ?? ""}
                            />
                            <div className="flex gap-2">
                              <Button
                                disabled={edit.isPending}
                                onClick={() => edit.mutate(editing)}
                                variant="primary"
                              >
                                保存编辑
                              </Button>
                              <Button
                                disabled={edit.isPending}
                                onClick={() => setEditing(null)}
                              >
                                取消
                              </Button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <strong>{item.title}</strong>
                            <p>{item.description}</p>
                            {item.due ? <small>{item.due}</small> : null}
                          </>
                        )}
                      </div>
                      <Badge>{item.status}</Badge>
                      <Button
                        disabled={patch.isPending}
                        onClick={() =>
                          patch.mutate({
                            item,
                            status:
                              item.status === "completed"
                                ? "pending"
                                : "completed",
                          })
                        }
                      >
                        {item.status === "completed" ? "恢复" : "完成"}
                      </Button>
                      <Button
                        disabled={edit.isPending}
                        onClick={() => setEditing(item)}
                      >
                        编辑
                      </Button>
                      <Button
                        disabled={convert.isPending}
                        onClick={() => convert.mutate(item)}
                      >
                        转为日程
                      </Button>
                      <Button
                        disabled={remove.isPending}
                        onClick={() => remove.mutate(item)}
                        variant="danger"
                      >
                        删除
                      </Button>
                    </li>
                  ))}
                  {!todos.data?.some(quadrant.filter) ? (
                    <li className="todo-card todo-card--empty">暂无待办</li>
                  ) : null}
                </ul>
              </section>
            ))
          ) : (
            <section className="todo-quadrant todo-quadrant--list">
              <ul>
                {todos.data?.map((item) => (
                  <li className="todo-card" key={item.id}>
                    <div className="flex-1">
                      <strong>{item.title}</strong>
                      <p>{item.description}</p>
                      {item.due ? <small>{item.due}</small> : null}
                    </div>
                    <Badge>{item.status}</Badge>
                    <Button
                      disabled={patch.isPending}
                      onClick={() =>
                        patch.mutate({
                          item,
                          status:
                            item.status === "completed"
                              ? "pending"
                              : "completed",
                        })
                      }
                    >
                      {item.status === "completed" ? "恢复" : "完成"}
                    </Button>
                    <Button
                      disabled={edit.isPending}
                      onClick={() => setEditing(item)}
                    >
                      编辑
                    </Button>
                    <Button
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(item)}
                      variant="danger"
                    >
                      删除
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
    </section>
  );
}
