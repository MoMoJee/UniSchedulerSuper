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
  EventContentArg,
  EventInput,
} from "@fullcalendar/core";
import timeGridPlugin from "@fullcalendar/timegrid";
import {
  BellPlus,
  CalendarDays,
  CalendarPlus,
  Check,
  Filter,
  RefreshCw,
  Settings2,
  Users,
} from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import type { PlannerOccurrence } from "../../api/mappers";
import { plannerApi } from "../../api/planner";
import { apiClient } from "../../api/http";
import { settingsApi } from "../../api/settings";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { CenteredModal } from "../../components/ui/centered-modal";
import { Badge } from "../../components/ui/status";
import { Popover } from "../../components/ui/overlays";
import { useCalendarProjection } from "./hooks";
import { EventEditor, type NewEventDraft } from "./event-editor";
import { GroupManager } from "./group-manager";
import { ReminderPanel } from "./reminder-panel";
import styles from "./planner-workspace.module.css";

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

function semesterLabel(
  date: string,
  periods: Array<{
    name: string;
    year?: number;
    month: number;
    day: number;
  }>,
) {
  const current = new Date(`${date}T12:00:00`);
  const candidates = periods
    .map((period) => ({
      period,
      start: new Date(
        period.year ?? current.getFullYear(),
        Math.max(0, period.month - 1),
        period.day,
        12,
      ),
    }))
    .filter((item) => item.start <= current)
    .sort((a, b) => b.start.getTime() - a.start.getTime());
  const active = candidates[0];
  if (!active) return null;
  const week =
    Math.floor(
      (current.getTime() - active.start.getTime()) / (7 * 24 * 60 * 60 * 1000),
    ) + 1;
  return week > 0 ? `${active.period.name} · 第 ${week} 周` : null;
}

function CalendarEventContent({ event }: EventContentArg) {
  const item = event.extendedProps.occurrence as PlannerOccurrence;
  const colors = event.extendedProps.shareColors as string[];
  return (
    <div className="planner-event-content">
      {colors.length ? (
        <span
          aria-label={`已分享到 ${colors.length} 个分享组`}
          className="planner-share-dots"
        >
          {colors.map((color, index) => (
            <i key={`${color}-${index}`} style={{ backgroundColor: color }} />
          ))}
        </span>
      ) : null}
      <span className="planner-event-time">
        {event.start
          ? event.start.toLocaleTimeString("zh-CN", {
              hour: "2-digit",
              minute: "2-digit",
            })
          : ""}
      </span>
      <span className="planner-event-title">
        {item.type === "reminder" ? "提醒：" : ""}
        {item.title}
      </span>
    </div>
  );
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
    <CenteredModal
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
          {item.ddlAt ? (
            <p>
              <strong>DDL：</strong>
              {item.ddlAt}
            </p>
          ) : null}
          {item.importance || item.urgency ? (
            <p>
              <strong>四象限：</strong>
              {item.importance || "未设重要性"} / {item.urgency || "未设紧急性"}
            </p>
          ) : null}
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
    </CenteredModal>
  );
}

export function PlannerWorkspace({ username }: { username: string }) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const date = params.get("date") ?? new Date().toISOString().slice(0, 10);
  const view = params.get("view") ?? "dayGridMonth";
  const shareGroupId = params.get("share") ?? undefined;
  const recurrenceFilter = params.get("repeat") ?? "all";
  const ddlFilter = params.get("ddl") ?? "all";
  const [range, setRange] = useState(() => initialRange(date));
  const pendingCalendarLocation = useRef<{
    date: string;
    view: string;
  } | null>(null);
  const [selected, setSelected] = useState<PlannerOccurrence | null>(null);
  const [newEventDraft, setNewEventDraft] = useState<NewEventDraft | null>(
    null,
  );
  const [editorOpen, setEditorOpen] = useState(false);
  const [reminderOpen, setReminderOpen] = useState(false);
  const [groupsOpen, setGroupsOpen] = useState(false);
  const scopeTabs = useRef<HTMLElement>(null);
  const [showReminders, setShowReminders] = useState(
    params.get("reminders") !== "0",
  );
  const [groupIds, setGroupIds] = useState<string[]>(() =>
    (params.get("groups") ?? "").split(",").filter(Boolean),
  );
  const projection = useCalendarProjection(
    username,
    range.from,
    range.to,
    shareGroupId,
  );
  const selectedFromUrl = useMemo(() => {
    const selectedId = params.get("selected");
    if (!selectedId || !projection.data) return null;
    return (
      [...projection.data.occurrences, ...projection.data.reminders].find(
        (item) =>
          item.id === selectedId || item.occurrenceRef?.entityId === selectedId,
      ) ?? null
    );
  }, [params, projection.data]);
  const effectiveSelected = selected ?? selectedFromUrl;
  const shareGroups = useQuery({
    queryKey: ["share-groups", "planner-tabs"],
    queryFn: async () => {
      const result = await apiClient.request<{
        groups?: Array<Record<string, unknown>>;
      }>("/api/share-groups/my-groups/");
      return (result.groups ?? []).flatMap((group) =>
        typeof group.share_group_id === "string" &&
        typeof group.share_group_name === "string"
          ? [
              {
                id: group.share_group_id,
                name: group.share_group_name,
                color:
                  typeof group.share_group_color === "string"
                    ? group.share_group_color
                    : "var(--accent)",
              },
            ]
          : [],
      );
    },
    staleTime: 30_000,
  });
  const preferences = useQuery({
    queryKey: ["settings", "preferences"],
    queryFn: settingsApi.getPreferences,
    staleTime: 60_000,
  });
  const shareColorById = useMemo(
    () =>
      new Map((shareGroups.data ?? []).map((group) => [group.id, group.color])),
    [shareGroups.data],
  );
  const activeSemester = useMemo(
    () =>
      preferences.data?.show_week_number === false
        ? null
        : semesterLabel(date, preferences.data?.week_number_periods ?? []),
    [date, preferences.data],
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
      .filter(
        (item) => !groupIds.length || groupIds.includes(item.groupId ?? ""),
      )
      .filter((item) =>
        recurrenceFilter === "recurring"
          ? Boolean(item.occurrenceRef?.seriesId)
          : recurrenceFilter === "single"
            ? !item.occurrenceRef?.seriesId
            : true,
      )
      .filter((item) =>
        ddlFilter === "with"
          ? Boolean(item.ddlAt)
          : ddlFilter === "without"
            ? !item.ddlAt
            : true,
      )
      .map((item) => ({
        // A recurring definition may project many occurrences with the same
        // entity id. FullCalendar requires a unique render id per instance.
        id: [
          item.type,
          item.id,
          item.occurrenceRef?.recurrenceId ?? item.start,
        ].join(":"),
        title: `${item.type === "reminder" ? "提醒：" : ""}${item.title}`,
        start: item.start,
        end: item.end ?? undefined,
        allDay: item.isAllDay,
        editable: item.type === "event" && !item.readOnly,
        backgroundColor: item.readOnly
          ? "#7b8798"
          : item.type === "reminder"
            ? "#a05bd5"
            : (projection.data?.groups.find(
                (group) => group.id === item.groupId,
              )?.color ?? "#4f86c6"),
        classNames: item.shareGroupIds.length ? ["planner-event--shared"] : [],
        extendedProps: {
          occurrence: item,
          shareColors: item.shareGroupIds
            .map((id) => shareColorById.get(id))
            .filter((color): color is string => Boolean(color)),
        },
      }));
  }, [
    ddlFilter,
    groupIds,
    projection.data,
    recurrenceFilter,
    shareColorById,
    showReminders,
  ]);

  const toggleGroup = (nextId: string) => {
    const next = groupIds.includes(nextId)
      ? groupIds.filter((id) => id !== nextId)
      : [...groupIds, nextId];
    setGroupIds(next);
    updateUrl({ groups: next.length ? next.join(",") : null });
  };

  const updateUrl = (next: Record<string, string | null>) => {
    const copy = new URLSearchParams(params);
    Object.entries(next).forEach(([key, value]) =>
      value ? copy.set(key, value) : copy.delete(key),
    );
    setParams(copy, { replace: true });
  };

  // FullCalendar invokes datesSet while its React subtree is mounting. React
  // Router navigation at that point is a render-phase side effect and can
  // produce transient route resets, so persist the visible range afterwards.
  useEffect(() => {
    if (!pendingCalendarLocation.current) return;
    const copy = new URLSearchParams(params);
    copy.set("date", pendingCalendarLocation.current.date);
    copy.set("view", pendingCalendarLocation.current.view);
    setParams(copy, { replace: true });
    pendingCalendarLocation.current = null;
  }, [params, range, setParams]);

  return (
    <section
      className={`planner-workspace ${styles.root}`}
      aria-label="Planner 工作区"
    >
      <h1 className="sr-only">我的日程</h1>
      <div className="planner-toolbar planner-toolbar--compact">
        <div className="planner-toolbar__actions">
          <Button
            aria-label="创建日程"
            onClick={() => {
              setSelected(null);
              setNewEventDraft(null);
              setEditorOpen(true);
            }}
            variant="primary"
          >
            <CalendarPlus size={16} /> 创建日程
          </Button>
          <Button
            onClick={() => {
              setSelected(null);
              setReminderOpen(true);
            }}
          >
            <BellPlus size={16} /> 创建提醒
          </Button>
          <Button onClick={() => setGroupsOpen(true)}>
            <Users size={16} /> 日程组
          </Button>
          <Button
            aria-label="刷新当前日历窗口"
            onClick={() => projection.refetch()}
            variant="secondary"
          >
            <RefreshCw aria-hidden="true" size={16} />
            <span className="planner-toolbar__optional-label">刷新</span>
          </Button>
        </div>
        <div className="planner-toolbar__context">
          {activeSemester ? (
            <button
              className="semester-badge"
              onClick={() => navigate("/?surface=settings&settings=calendar")}
              type="button"
            >
              {activeSemester}
            </button>
          ) : null}
          <Popover
            trigger={
              <Button aria-label="打开日程筛选" variant="secondary">
                <Filter aria-hidden="true" size={16} /> 筛选
                {groupIds.length ? ` (${groupIds.length})` : ""}
              </Button>
            }
          >
            <div className="planner-filter-popover" aria-label="日程筛选">
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
                重复
                <select
                  aria-label="重复筛选"
                  onChange={(event) =>
                    updateUrl({
                      repeat:
                        event.target.value === "all"
                          ? null
                          : event.target.value,
                    })
                  }
                  value={recurrenceFilter}
                >
                  <option value="all">全部</option>
                  <option value="recurring">仅重复</option>
                  <option value="single">仅单次</option>
                </select>
              </label>
              <label>
                DDL
                <select
                  aria-label="DDL 筛选"
                  onChange={(event) =>
                    updateUrl({
                      ddl:
                        event.target.value === "all"
                          ? null
                          : event.target.value,
                    })
                  }
                  value={ddlFilter}
                >
                  <option value="all">全部</option>
                  <option value="with">有 DDL</option>
                  <option value="without">无 DDL</option>
                </select>
              </label>
              <fieldset className="group-filter-list">
                <legend>日程组（可多选）</legend>
                {projection.data?.groups.map((group) => (
                  <label key={group.id}>
                    <input
                      checked={groupIds.includes(group.id)}
                      onChange={() => toggleGroup(group.id)}
                      type="checkbox"
                    />
                    <span
                      className="group-color-dot"
                      style={{ background: group.color }}
                    />
                    {group.name}
                    {groupIds.includes(group.id) ? (
                      <Check aria-hidden="true" size={14} />
                    ) : null}
                  </label>
                ))}
                {!projection.data?.groups.length ? (
                  <small>暂无个人日程组</small>
                ) : null}
              </fieldset>
              {groupIds.length ||
              recurrenceFilter !== "all" ||
              ddlFilter !== "all" ||
              !showReminders ? (
                <Button
                  onClick={() => {
                    setGroupIds([]);
                    setShowReminders(true);
                    updateUrl({
                      groups: null,
                      reminders: null,
                      repeat: null,
                      ddl: null,
                    });
                  }}
                  variant="ghost"
                >
                  重置筛选
                </Button>
              ) : null}
              {shareGroupId ? <Badge>共享组投影</Badge> : null}
            </div>
          </Popover>
        </div>
      </div>
      <nav
        aria-label="日历范围"
        className="planner-scope-tabs"
        onWheel={(event) => {
          if (
            !scopeTabs.current ||
            Math.abs(event.deltaY) <= Math.abs(event.deltaX)
          )
            return;
          scopeTabs.current.scrollLeft += event.deltaY;
          event.preventDefault();
        }}
        ref={scopeTabs}
      >
        <Button
          aria-pressed={!shareGroupId}
          onClick={() => updateUrl({ share: null })}
          variant={!shareGroupId ? "primary" : "ghost"}
        >
          我的日程
        </Button>
        {shareGroups.data?.map((group) => (
          <Button
            aria-pressed={shareGroupId === group.id}
            key={group.id}
            onClick={() => updateUrl({ share: group.id })}
            variant={shareGroupId === group.id ? "primary" : "ghost"}
          >
            <span
              className="group-color-dot"
              style={{ background: group.color }}
            />{" "}
            {group.name}
          </Button>
        ))}
        <Button
          aria-label="管理分享组"
          onClick={() => navigate("/?surface=share")}
          variant="ghost"
        >
          <Settings2 size={15} /> 管理
        </Button>
      </nav>
      <div className={styles.calendarStage}>
        {projection.isFetching ? (
          <div aria-live="polite" className={styles.loadingOverlay}>
            <RefreshCw className="animate-spin" size={14} /> 正在更新日程
          </div>
        ) : null}
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
        <FullCalendar
          buttonHints={{
            next: "下一页",
            prev: "上一页",
            today: "回到今天",
          }}
          buttonText={{
            today: "今天",
            month: "月",
            week: "周",
            day: "日",
            list: "列表",
          }}
          datesSet={(arg) => {
            const next = isoRange(arg);
            pendingCalendarLocation.current = {
              date: arg.startStr.slice(0, 10),
              view: arg.view.type,
            };
            setRange(next);
          }}
          eventClick={(arg: EventClickArg) =>
            setSelected(arg.event.extendedProps.occurrence as PlannerOccurrence)
          }
          eventContent={CalendarEventContent}
          eventDrop={onDragOrResize}
          eventResize={onDragOrResize}
          events={events}
          firstDay={1}
          select={(arg) => {
            setSelected(null);
            setNewEventDraft({
              start: arg.start.toISOString(),
              end: arg.end.toISOString(),
              isAllDay: arg.allDay,
              groupId: groupIds.length === 1 ? groupIds[0] : null,
            });
            setEditorOpen(true);
          }}
          headerToolbar={{
            left: "prev,next today",
            center: "title",
            right: "dayGridMonth,timeGridWeek,timeGridTwoDay,listWeek",
          }}
          height="100%"
          initialDate={date}
          initialView={view}
          locale="zh-cn"
          plugins={[
            dayGridPlugin,
            timeGridPlugin,
            listPlugin,
            interactionPlugin,
          ]}
          selectable
          selectMirror
          views={{
            timeGridTwoDay: {
              type: "timeGrid",
              duration: { days: 2 },
              buttonText: "2日",
            },
          }}
          viewDidMount={(arg) => {
            arg.el
              .closest(".fc")
              ?.querySelectorAll('.fc-icon[role="img"]')
              .forEach((icon) => icon.setAttribute("aria-hidden", "true"));
          }}
        />
        {!projection.isFetching && !projection.error && events.length === 0 ? (
          <div className="empty-state">
            <CalendarDays aria-hidden="true" size={28} />
            当前查询窗口没有可见项目。
          </div>
        ) : null}
      </div>
      <DetailSheet
        item={effectiveSelected}
        onClose={() => {
          setSelected(null);
          if (params.get("selected")) updateUrl({ selected: null });
        }}
        onEdit={(item) => {
          setSelected(item);
          if (item.type === "reminder") setReminderOpen(true);
          else setEditorOpen(true);
        }}
      />
      <EventEditor
        groups={projection.data?.groups ?? []}
        initialDraft={newEventDraft}
        key={`event-editor-${selected?.id ?? newEventDraft?.start ?? "new"}`}
        item={selected}
        onClose={() => {
          setEditorOpen(false);
          setSelected(null);
          setNewEventDraft(null);
        }}
        open={editorOpen}
      />
      <ReminderPanel
        key={`reminder-editor-${selected?.id ?? "new"}`}
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
