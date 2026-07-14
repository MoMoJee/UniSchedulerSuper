import dayGridPlugin from "@fullcalendar/daygrid";
import interactionPlugin, {
  type EventResizeDoneArg,
} from "@fullcalendar/interaction";
import listPlugin from "@fullcalendar/list";
import FullCalendar from "@fullcalendar/react";
import type {
  DatesSetArg,
  EventDropArg,
  EventClickArg,
  EventInput,
} from "@fullcalendar/core";
import timeGridPlugin from "@fullcalendar/timegrid";
import { CalendarDays, RefreshCw } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { PlannerOccurrence } from "../../api/mappers";
import { plannerApi } from "../../api/planner";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { Sheet } from "../../components/ui/sheet";
import { Badge, Skeleton } from "../../components/ui/status";
import { useCalendarProjection } from "./hooks";
import { EventEditor } from "./event-editor";
import { GroupManager } from "./group-manager";
import { ReminderPanel } from "./reminder-panel";

function ReminderActions({ item }: { item: PlannerOccurrence }) {
  const client = useQueryClient();
  const action = useMutation({
    mutationFn: (kind: "complete" | "dismiss" | "snooze") => {
      if (!item.occurrenceRef)
        throw new Error("提醒实例缺少服务端 occurrence_ref。");
      return plannerApi.actOnReminderOccurrence(
        kind,
        {
          entity_id: item.occurrenceRef.entityId,
          series_id: item.occurrenceRef.seriesId,
          recurrence_id: item.occurrenceRef.recurrenceId,
          source_version: item.occurrenceRef.sourceVersion,
        },
        item.occurrenceRef.sourceVersion,
        kind === "snooze"
          ? new Date(Date.now() + 60 * 60 * 1000).toISOString()
          : undefined,
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["planner"] }),
  });
  return (
    <div className="flex flex-wrap gap-2">
      <Button
        disabled={action.isPending}
        onClick={() => action.mutate("complete")}
      >
        完成
      </Button>
      <Button
        disabled={action.isPending}
        onClick={() => action.mutate("dismiss")}
      >
        忽略
      </Button>
      <Button
        disabled={action.isPending}
        onClick={() => action.mutate("snooze")}
      >
        延后 1 小时
      </Button>
      {action.error ? <ApiErrorNotice error={action.error} /> : null}
    </div>
  );
}

function isoRange(arg: DatesSetArg) {
  return { from: arg.start.toISOString(), to: arg.end.toISOString() };
}

function initialRange(date: string) {
  const start = new Date(`${date}T00:00:00`);
  const end = new Date(start);
  end.setDate(end.getDate() + 42);
  return { from: start.toISOString(), to: end.toISOString() };
}

function recurrenceText(item: PlannerOccurrence) {
  return item.occurrenceRef?.seriesId ? "重复系列实例" : "单次项目";
}

function DetailSheet({
  item,
  onClose,
  onEdit,
}: {
  item: PlannerOccurrence | null;
  onClose: () => void;
  onEdit: (item: PlannerOccurrence) => void;
}) {
  return (
    <Sheet
      onOpenChange={(open) => !open && onClose()}
      open={item !== null}
      title={item?.title ?? "详情"}
    >
      {item ? (
        <div className="mt-4 space-y-3 text-sm">
          <p>{item.description || "没有描述。"}</p>
          <p>
            <strong>时间：</strong>
            {item.start}
            {item.end ? ` – ${item.end}` : ""}
          </p>
          <p>
            <strong>类型：</strong>
            {item.type === "reminder" ? "提醒" : "日程"}；{recurrenceText(item)}
          </p>
          {item.readOnly ? (
            <Badge>共享只读：{item.ownerUsername ?? "其他成员"}</Badge>
          ) : (
            <Badge>个人可编辑项目</Badge>
          )}
          {item.occurrenceRef ? (
            <p className="text-[var(--text-muted)]">
              该实例由服务端 occurrence_ref 标识；编辑能力将在 FR-4 按范围开启。
            </p>
          ) : null}
          {!item.readOnly && item.type === "event" ? (
            <Button onClick={() => onEdit(item)} variant="primary">
              编辑日程
            </Button>
          ) : null}
          {!item.readOnly && item.type === "reminder" ? (
            <>
              <ReminderActions item={item} />
              <Button onClick={() => onEdit(item)} variant="primary">
                编辑整个提醒系列
              </Button>
            </>
          ) : null}
        </div>
      ) : null}
    </Sheet>
  );
}

export function PlannerWorkspace({ username }: { username: string }) {
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? new Date().toISOString().slice(0, 10);
  const view = params.get("view") ?? "dayGridMonth";
  const shareGroupId = params.get("share") ?? undefined;
  const [range, setRange] = useState(() => initialRange(date));
  const [selected, setSelected] = useState<PlannerOccurrence | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [reminderOpen, setReminderOpen] = useState(false);
  const [groupsOpen, setGroupsOpen] = useState(false);
  const [showReminders, setShowReminders] = useState(
    params.get("reminders") !== "0",
  );
  const [groupId, setGroupId] = useState(params.get("group") ?? "");
  const projection = useCalendarProjection(
    username,
    range.from,
    range.to,
    shareGroupId,
  );
  const client = useQueryClient();
  const moveEvent = useMutation({
    mutationFn: async ({
      item,
      start,
      end,
    }: {
      item: PlannerOccurrence;
      start: Date;
      end: Date | null;
    }) => {
      if (item.readOnly || item.type !== "event")
        throw new Error("共享只读项目不能移动。");
      if (item.occurrenceRef?.seriesId)
        throw new Error("重复日程需要选择编辑范围。");
      return plannerApi.patchEvent(
        item.occurrenceRef?.entityId ?? item.id,
        {
          start: start.toISOString(),
          end: (
            end ?? new Date(start.getTime() + 60 * 60 * 1000)
          ).toISOString(),
        },
        {
          expectedVersion: item.occurrenceRef?.sourceVersion ?? 1,
          scope: "all",
        },
      );
    },
    onSuccess: () => client.invalidateQueries({ queryKey: ["planner"] }),
  });
  const onDragOrResize = (arg: EventDropArg | EventResizeDoneArg) => {
    const item = arg.event.extendedProps.occurrence as PlannerOccurrence;
    if (item.occurrenceRef?.seriesId) {
      arg.revert();
      setSelected(item);
      setEditorOpen(true);
      return;
    }
    moveEvent.mutate({
      item,
      start: arg.event.start ?? new Date(item.start),
      end: arg.event.end,
    });
  };

  const events = useMemo<EventInput[]>(() => {
    if (!projection.data) return [];
    const all = showReminders
      ? [...projection.data.occurrences, ...projection.data.reminders]
      : projection.data.occurrences;
    return all
      .filter((item) => !groupId || item.groupId === groupId)
      .map((item) => ({
        id: item.id,
        title: `${item.type === "reminder" ? "提醒：" : ""}${item.title}`,
        start: item.start,
        end: item.end ?? undefined,
        allDay: item.isAllDay,
        editable: item.type === "event" && !item.readOnly,
        backgroundColor: item.readOnly
          ? "#7b8798"
          : item.type === "reminder"
            ? "#a05bd5"
            : "#1769e0",
        extendedProps: { occurrence: item },
      }));
  }, [groupId, projection.data, showReminders]);

  const updateUrl = (next: Record<string, string | null>) => {
    const copy = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) =>
      value ? copy.set(key, value) : copy.delete(key),
    );
    setParams(copy, { replace: true });
  };

  return (
    <section className="planner-workspace" aria-label="Planner 工作区">
      <div className="planner-toolbar">
        <div>
          <Badge>FR-4 日程工作区</Badge>
          <h1 className="mt-2 text-2xl font-semibold">日程工作区</h1>
        </div>
        <div className="flex gap-2">
          <Button
            onClick={() => {
              setSelected(null);
              setEditorOpen(true);
            }}
            variant="primary"
          >
            创建日程
          </Button>
          <Button
            onClick={() => {
              setSelected(null);
              setReminderOpen(true);
            }}
          >
            创建提醒
          </Button>
          <Button onClick={() => setGroupsOpen(true)}>管理日程组</Button>
          <Button
            aria-label="刷新当前日历窗口"
            onClick={() => projection.refetch()}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" size={16} />
            刷新
          </Button>
        </div>
      </div>
      <div className="planner-filters" aria-label="日程筛选">
        <label>
          <input
            checked={showReminders}
            onChange={(event) => {
              setShowReminders(event.target.checked);
              updateUrl({ reminders: event.target.checked ? null : "0" });
            }}
            type="checkbox"
          />{" "}
          显示提醒
        </label>
        <label>
          日程组
          <select
            aria-label="按日程组筛选"
            value={groupId}
            onChange={(event) => {
              setGroupId(event.target.value);
              updateUrl({ group: event.target.value || null });
            }}
          >
            <option value="">全部日程组</option>
            {projection.data?.groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        {shareGroupId ? <Badge>共享组投影</Badge> : null}
      </div>
      {projection.isLoading ? <Skeleton className="h-[36rem]" /> : null}
      {projection.error ? (
        <ApiErrorNotice
          error={projection.error}
          onRetry={() => projection.refetch()}
        />
      ) : null}
      {moveEvent.error ? (
        <ApiErrorNotice
          error={moveEvent.error}
          onRetry={() => projection.refetch()}
        />
      ) : null}
      {!projection.isLoading && !projection.error ? (
        <FullCalendar
          datesSet={(arg) => {
            const next = isoRange(arg);
            setRange(next);
            updateUrl({ date: arg.startStr.slice(0, 10), view: arg.view.type });
          }}
          eventClick={(arg: EventClickArg) =>
            setSelected(arg.event.extendedProps.occurrence as PlannerOccurrence)
          }
          eventDrop={onDragOrResize}
          eventResize={onDragOrResize}
          events={events}
          firstDay={1}
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridDay,listWeek",
          }}
          height="auto"
          initialDate={date}
          initialView={view}
          locale="zh-cn"
          plugins={[
            dayGridPlugin,
            timeGridPlugin,
            listPlugin,
            interactionPlugin,
          ]}
          selectable={false}
        />
      ) : null}
      {!projection.isLoading && !projection.error && events.length === 0 ? (
        <div className="empty-state">
          <CalendarDays aria-hidden="true" size={28} />
          当前查询窗口没有可见项目。
        </div>
      ) : null}
      <DetailSheet
        item={selected}
        onClose={() => setSelected(null)}
        onEdit={(item) =>
          item.type === "reminder" ? setReminderOpen(true) : setEditorOpen(true)
        }
      />
      <EventEditor
        groups={projection.data?.groups ?? []}
        key={selected?.id ?? "new-event"}
        item={selected}
        onClose={() => {
          setEditorOpen(false);
          setSelected(null);
        }}
        open={editorOpen}
      />
      <ReminderPanel
        key={selected?.id ?? "new-reminder"}
        item={selected?.type === "reminder" ? selected : null}
        onClose={() => {
          setReminderOpen(false);
          setSelected(null);
        }}
        open={reminderOpen}
      />
      <GroupManager
        groups={projection.data?.groups ?? []}
        onClose={() => setGroupsOpen(false)}
        open={groupsOpen}
      />
    </section>
  );
}
