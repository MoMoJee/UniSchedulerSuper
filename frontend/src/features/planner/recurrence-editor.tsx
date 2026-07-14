import { useMemo } from "react";

import { Input, Select } from "../../components/ui/form";

export type RecurrenceFrequency =
  "none" | "DAILY" | "WEEKLY" | "MONTHLY" | "YEARLY";

export interface RecurrenceDraft {
  frequency: RecurrenceFrequency;
  interval: number;
  byDay: string[];
  count: string;
  until: string;
}

export function parseRRule(rrule: string | null | undefined): RecurrenceDraft {
  const fields = new Map<string, string>();
  for (const part of (rrule ?? "").split(";")) {
    const separator = part.indexOf("=");
    if (separator < 1) continue;
    const key = part.slice(0, separator);
    const value = part.slice(separator + 1);
    if (value) fields.set(key, value);
  }
  const frequency = fields.get("FREQ");
  return {
    frequency:
      frequency === "DAILY" ||
      frequency === "WEEKLY" ||
      frequency === "MONTHLY" ||
      frequency === "YEARLY"
        ? frequency
        : "none",
    interval: Math.max(1, Number(fields.get("INTERVAL") ?? 1) || 1),
    byDay: (fields.get("BYDAY") ?? "")
      .split(",")
      .filter((value) =>
        ["MO", "TU", "WE", "TH", "FR", "SA", "SU"].includes(value),
      ),
    count: fields.get("COUNT") ?? "",
    until: fields.get("UNTIL") ?? "",
  };
}

export function buildRRule(draft: RecurrenceDraft): string | null {
  if (draft.frequency === "none") return null;
  if (
    !Number.isInteger(draft.interval) ||
    draft.interval < 1 ||
    draft.interval > 365
  )
    throw new Error("重复间隔必须是 1 到 365 的整数。");
  if (draft.count && (!/^\d+$/.test(draft.count) || Number(draft.count) < 1))
    throw new Error("重复次数必须是正整数。");
  if (draft.count && draft.until)
    throw new Error("重复规则不能同时设置次数和结束日期。");
  const fields = [`FREQ=${draft.frequency}`];
  if (draft.interval !== 1) fields.push(`INTERVAL=${draft.interval}`);
  if (draft.frequency === "WEEKLY" && draft.byDay.length) {
    fields.push(`BYDAY=${draft.byDay.join(",")}`);
  }
  if (draft.count) fields.push(`COUNT=${draft.count}`);
  if (draft.until) {
    const date = new Date(draft.until);
    if (Number.isNaN(date.getTime())) throw new Error("重复结束日期无效。");
    fields.push(
      `UNTIL=${date
        .toISOString()
        .replace(/[-:]/g, "")
        .replace(/\.\d{3}/, "")}`,
    );
  }
  return fields.join(";");
}

const weekdays = [
  ["MO", "周一"],
  ["TU", "周二"],
  ["WE", "周三"],
  ["TH", "周四"],
  ["FR", "周五"],
  ["SA", "周六"],
  ["SU", "周日"],
] as const;

export function RecurrenceEditor({
  draft,
  onChange,
  label = "重复规则",
}: {
  draft: RecurrenceDraft;
  onChange: (next: RecurrenceDraft) => void;
  label?: string;
}) {
  const selectedDays = useMemo(() => new Set(draft.byDay), [draft.byDay]);
  return (
    <fieldset className="space-y-2">
      <legend>{label}</legend>
      <Select
        onValueChange={(value) =>
          onChange({ ...draft, frequency: value as RecurrenceFrequency })
        }
        options={[
          { value: "none", label: "不重复" },
          { value: "DAILY", label: "每天" },
          { value: "WEEKLY", label: "每周" },
          { value: "MONTHLY", label: "每月" },
          { value: "YEARLY", label: "每年" },
        ]}
        placeholder="重复规则"
        value={draft.frequency}
      />
      {draft.frequency !== "none" ? (
        <>
          <label>
            间隔
            <Input
              min="1"
              onChange={(event) =>
                onChange({
                  ...draft,
                  interval: Number(event.target.value) || 0,
                })
              }
              type="number"
              value={draft.interval}
            />
          </label>
          {draft.frequency === "WEEKLY" ? (
            <div aria-label="每周重复日" className="flex flex-wrap gap-2">
              {weekdays.map(([value, text]) => (
                <label key={value}>
                  <input
                    checked={selectedDays.has(value)}
                    onChange={() =>
                      onChange({
                        ...draft,
                        byDay: selectedDays.has(value)
                          ? draft.byDay.filter((day) => day !== value)
                          : [...draft.byDay, value],
                      })
                    }
                    type="checkbox"
                  />{" "}
                  {text}
                </label>
              ))}
            </div>
          ) : null}
          <label>
            重复次数（留空即不按次数结束）
            <Input
              min="1"
              onChange={(event) =>
                onChange({ ...draft, count: event.target.value, until: "" })
              }
              type="number"
              value={draft.count}
            />
          </label>
          <label>
            结束日期（留空即无限）
            <Input
              onChange={(event) =>
                onChange({ ...draft, until: event.target.value, count: "" })
              }
              type="datetime-local"
              value={draft.until}
            />
          </label>
        </>
      ) : null}
    </fieldset>
  );
}
