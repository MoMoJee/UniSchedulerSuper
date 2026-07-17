import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import type { PlannerOccurrence } from "../../api/mappers";
import { plannerApi } from "../../api/planner";
import { ApiErrorNotice } from "../../components/shared/api-error-notice";
import { Button } from "../../components/ui/button";
import { Input, Textarea } from "../../components/ui/form";
import { CenteredModal } from "../../components/ui/centered-modal";
import {
  buildRRule,
  parseRRule,
  RecurrenceEditor,
  type RecurrenceDraft,
} from "./recurrence-editor";

export function ReminderPanel({
  open,
  item,
  onClose,
}: {
  open: boolean;
  item: PlannerOccurrence | null;
  onClose: () => void;
}) {
  const [title, setTitle] = useState(item?.title ?? "");
  const [content, setContent] = useState(item?.description ?? "");
  const [trigger, setTrigger] = useState(
    item?.start?.slice(0, 16) ?? new Date().toISOString().slice(0, 16),
  );
  const [recurrence, setRecurrence] = useState<RecurrenceDraft>(() =>
    parseRRule(item?.recurrenceRRule),
  );
  const [recurrenceChanged, setRecurrenceChanged] = useState(false);
  const client = useQueryClient();
  const mutation = useMutation({
    mutationFn: () => {
      if (!title.trim()) throw new Error("标题不能为空。");
      const recurrenceRule = buildRRule(recurrence);
      const payload = {
        title: title.trim(),
        content,
        trigger: new Date(trigger).toISOString(),
        tzid: "Asia/Shanghai",
        ...(!item || recurrenceChanged
          ? { recurrence: recurrenceRule ? { rrule: recurrenceRule } : null }
          : {}),
      };
      if (!item) return plannerApi.createReminder(payload);
      const ref = item.occurrenceRef
        ? {
            entity_id: item.occurrenceRef.entityId,
            series_id: item.occurrenceRef.seriesId,
            recurrence_id: item.occurrenceRef.recurrenceId,
            source_version: item.occurrenceRef.sourceVersion,
          }
        : undefined;
      return plannerApi.patchReminder(
        item.occurrenceRef?.entityId ?? item.id,
        payload,
        {
          expectedVersion: item.occurrenceRef?.sourceVersion ?? 1,
          scope: "all",
          occurrenceRef: ref,
        },
      );
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["planner"] });
      onClose();
    },
  });
  const deleteMutation = useMutation({
    mutationFn: () => {
      if (!item) throw new Error("尚未创建的提醒不能删除。");
      const ref = item.occurrenceRef
        ? {
            entity_id: item.occurrenceRef.entityId,
            series_id: item.occurrenceRef.seriesId,
            recurrence_id: item.occurrenceRef.recurrenceId,
            source_version: item.occurrenceRef.sourceVersion,
          }
        : undefined;
      return plannerApi.deleteReminder(
        item.occurrenceRef?.entityId ?? item.id,
        {
          expectedVersion: item.occurrenceRef?.sourceVersion ?? 1,
          scope: "all",
          occurrenceRef: ref,
        },
      );
    },
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["planner"] });
      onClose();
    },
  });
  return (
    <CenteredModal
      onOpenChange={(nextOpen) => !nextOpen && onClose()}
      open={open}
      title={item ? "编辑提醒（整个系列）" : "创建提醒"}
      size="lg"
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
            onChange={(event) => setTitle(event.target.value)}
            value={title}
          />
        </label>
        <label>
          内容
          <Textarea
            onChange={(event) => setContent(event.target.value)}
            value={content}
          />
        </label>
        <label>
          触发时间
          <Input
            onChange={(event) => setTrigger(event.target.value)}
            type="datetime-local"
            value={trigger}
          />
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
            未改动重复控件时保留服务端现有规则。
          </p>
        ) : null}
        {item ? (
          <p>
            新版 Reminder 定义编辑只支持整个系列；单次操作仅可完成、忽略或延后。
          </p>
        ) : null}
        {mutation.error || deleteMutation.error ? (
          <ApiErrorNotice error={mutation.error ?? deleteMutation.error} />
        ) : null}
        <div className="flex gap-2">
          <Button
            disabled={mutation.isPending || deleteMutation.isPending}
            type="submit"
            variant="primary"
          >
            保存
          </Button>
          {item ? (
            <Button
              disabled={mutation.isPending || deleteMutation.isPending}
              onClick={() => deleteMutation.mutate()}
              variant="danger"
            >
              删除整个系列
            </Button>
          ) : null}
        </div>
      </form>
    </CenteredModal>
  );
}
