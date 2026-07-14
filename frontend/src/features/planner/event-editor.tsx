import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { PlannerOccurrence } from "../../api/mappers";
import { plannerApi, type PlannerScope } from "../../api/planner";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { Input, Select, Textarea } from "../../components/ui/form";
import { Sheet } from "../../components/ui/sheet";
import {
  buildRRule,
  parseRRule,
  RecurrenceEditor,
  type RecurrenceDraft,
} from "./recurrence-editor";
import type { EditableGroup } from "./group-manager";

function localDateTime(value?: string | null) {
  return value ? value.slice(0, 16) : new Date().toISOString().slice(0, 16);
}

export function EventEditor({
  open,
  item,
  groups,
  onClose,
}: {
  open: boolean;
  item: PlannerOccurrence | null;
  groups: EditableGroup[];
  onClose: () => void;
}) {
  const [title, setTitle] = useState(item?.title ?? "");
  const [description, setDescription] = useState(item?.description ?? "");
  const [start, setStart] = useState(localDateTime(item?.start));
  const [end, setEnd] = useState(localDateTime(item?.end));
  const [allDay, setAllDay] = useState(item?.isAllDay ?? false);
  const [groupId, setGroupId] = useState(item?.groupId ?? "");
  const [recurrence, setRecurrence] = useState<RecurrenceDraft>(() =>
    parseRRule(item?.recurrenceRRule),
  );
  const [recurrenceChanged, setRecurrenceChanged] = useState(false);
  const [scope, setScope] = useState<PlannerScope>("all");
  const queryClient = useQueryClient();
  const mutation = useMutation({
    mutationFn: async () => {
      if (!title.trim()) throw new Error("标题不能为空。");
      if (!start || !end || new Date(start) >= new Date(end))
        throw new Error("结束时间必须晚于开始时间。");
      const recurrenceRule = buildRRule(recurrence);
      const payload = {
        title: title.trim(),
        description,
        start: new Date(start).toISOString(),
        end: new Date(end).toISOString(),
        tzid: "Asia/Shanghai",
        is_all_day: allDay,
        group_id: groupId || null,
        ...(!item || recurrenceChanged
          ? { recurrence: recurrenceRule ? { rrule: recurrenceRule } : null }
          : {}),
      };
      if (!item) return plannerApi.createEvent(payload);
      const ref = item.occurrenceRef
        ? {
            entity_id: item.occurrenceRef.entityId,
            series_id: item.occurrenceRef.seriesId,
            recurrence_id: item.occurrenceRef.recurrenceId,
            source_version: item.occurrenceRef.sourceVersion,
          }
        : undefined;
      return plannerApi.patchEvent(
        item.occurrenceRef?.entityId ?? item.id,
        payload,
        {
          expectedVersion: item.occurrenceRef?.sourceVersion ?? 1,
          scope,
          occurrenceRef: ref,
        },
      );
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["planner"] });
      onClose();
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!item) throw new Error("尚未创建的日程不能删除。");
      const ref = item.occurrenceRef
        ? {
            entity_id: item.occurrenceRef.entityId,
            series_id: item.occurrenceRef.seriesId,
            recurrence_id: item.occurrenceRef.recurrenceId,
            source_version: item.occurrenceRef.sourceVersion,
          }
        : undefined;
      return plannerApi.deleteEvent(item.occurrenceRef?.entityId ?? item.id, {
        expectedVersion: item.occurrenceRef?.sourceVersion ?? 1,
        scope,
        occurrenceRef: ref,
      });
    },
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["planner"] });
      onClose();
    },
  });
  const recurring = Boolean(item?.occurrenceRef?.seriesId);
  return (
    <Sheet
      onOpenChange={(nextOpen) => !nextOpen && onClose()}
      open={open}
      title={item ? "编辑日程" : "创建日程"}
    >
      <form
        className="mt-4 space-y-3"
        onSubmit={(event) => {
          event.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          标题
          <Input
            autoFocus
            onChange={(event) => setTitle(event.target.value)}
            value={title}
          />
        </label>
        <label>
          描述
          <Textarea
            onChange={(event) => setDescription(event.target.value)}
            value={description}
          />
        </label>
        <label>
          开始
          <Input
            onChange={(event) => setStart(event.target.value)}
            type="datetime-local"
            value={start}
          />
        </label>
        <label>
          结束
          <Input
            onChange={(event) => setEnd(event.target.value)}
            type="datetime-local"
            value={end}
          />
        </label>
        <label>
          <input
            checked={allDay}
            onChange={(event) => setAllDay(event.target.checked)}
            type="checkbox"
          />{" "}
          全天日程
        </label>
        <label>
          日程组
          <select
            aria-label="日程组"
            onChange={(event) => setGroupId(event.target.value)}
            value={groupId}
          >
            <option value="">不分组</option>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
        </label>
        <RecurrenceEditor
          draft={recurrence}
          label="重复规则"
          onChange={(next) => {
            setRecurrence(next);
            setRecurrenceChanged(true);
          }}
        />
        {item && !recurrenceChanged ? (
          <p className="text-[var(--text-muted)]">
            未改动重复控件时保留服务端现有规则；选择任一规则后才提交变更。
          </p>
        ) : null}
        {recurring ? (
          <label>
            应用范围
            <Select
              onValueChange={(value) => setScope(value as PlannerScope)}
              options={[
                { value: "single", label: "仅此实例" },
                { value: "future", label: "此实例及以后" },
                { value: "all", label: "整个系列" },
              ]}
              placeholder="整个系列"
              value={scope}
            />
          </label>
        ) : null}
        {mutation.error ? <ApiErrorNotice error={mutation.error} /> : null}
        <div className="flex gap-2">
          <Button
            disabled={mutation.isPending || deleteMutation.isPending}
            type="submit"
            variant="primary"
          >
            {mutation.isPending ? "保存中…" : "保存"}
          </Button>
          {item ? (
            <Button
              disabled={mutation.isPending || deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              variant="danger"
            >
              {deleteMutation.isPending ? "删除中…" : "删除"}
            </Button>
          ) : null}
        </div>
      </form>
    </Sheet>
  );
}
