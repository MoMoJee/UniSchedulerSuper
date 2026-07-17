import { useQuery, useQueryClient } from "@tanstack/react-query";

import {
  mapPlannerOccurrence,
  type PlannerOccurrence,
} from "../../api/mappers";
import { plannerApi } from "../../api/planner";
import { plannerKeys } from "../../api/queryKeys";

function recurrenceRulesByEntity(
  definitions: Array<Record<string, unknown>>,
  idField: "event_id" | "reminder_id",
) {
  return new Map(
    definitions.flatMap((definition) => {
      const id = definition[idField];
      if (typeof id !== "string") return [];
      const recurrence = definition.recurrence;
      const rule =
        typeof recurrence === "object" &&
        recurrence !== null &&
        typeof (recurrence as Record<string, unknown>).rrule === "string"
          ? ((recurrence as Record<string, unknown>).rrule as string)
          : null;
      return [[id, rule] as const];
    }),
  );
}

function withDefinitionRule(
  value: Record<string, unknown>,
  rules: Map<string, string | null>,
) {
  const occurrence = mapPlannerOccurrence(value);
  const entityId = occurrence.occurrenceRef?.entityId ?? occurrence.id;
  return rules.has(entityId)
    ? { ...occurrence, recurrenceRRule: rules.get(entityId) ?? null }
    : occurrence;
}

export interface CalendarProjection {
  occurrences: PlannerOccurrence[];
  reminders: PlannerOccurrence[];
  groups: Array<{ id: string; name: string; color: string; version: number }>;
}

export function useCalendarProjection(
  username: string,
  from: string,
  to: string,
  shareGroupId?: string,
) {
  return useQuery({
    queryKey: [
      ...plannerKeys.calendar(username, from, to, {
        shareGroupId: shareGroupId ?? "",
      }),
      "projection",
    ],
    queryFn: async ({ signal }): Promise<CalendarProjection> => {
      if (shareGroupId) {
        const [groups, shared] = await Promise.all([
          plannerApi.listGroups(signal),
          plannerApi.listSharedOccurrences(shareGroupId, from, to, signal),
        ]);
        return {
          occurrences: (shared.occurrences ?? []).map((value) =>
            withDefinitionRule(value, new Map()),
          ),
          reminders: [],
          groups: mapGroups(groups.groups ?? []),
        };
      }
      const [events, eventDefinitions, reminders, reminderDefinitions, groups] =
        await Promise.all([
          plannerApi.listEventOccurrences(from, to, signal),
          plannerApi.listEventDefinitions(from, to, signal),
          plannerApi.listReminders(from, to, signal),
          plannerApi.listReminders(undefined, undefined, signal),
          plannerApi.listGroups(signal),
        ]);
      const eventRules = recurrenceRulesByEntity(
        eventDefinitions.definitions ?? [],
        "event_id",
      );
      const reminderRules = recurrenceRulesByEntity(
        reminderDefinitions.reminders ?? [],
        "reminder_id",
      );
      return {
        // A shared scope is a separate projection, never an additive overlay.
        // Falling back to personal data here previously made every share tab look
        // like "我的日程" and could expose unrelated personal occurrences.
        occurrences: (events.occurrences ?? []).map((value) =>
          withDefinitionRule(value, eventRules),
        ),
        reminders: (reminders.occurrences ?? []).map((value) =>
          withDefinitionRule(value, reminderRules),
        ),
        groups: mapGroups(groups.groups ?? []),
      };
    },
    // 日历切换、面板重渲染不应重复拉取六个投影端点；显式刷新、编辑成功和
    // Agent 工具完成都会主动失效该 query，因而这里仍然保持及时一致。
    staleTime: 30_000,
    refetchOnWindowFocus: false,
  });
}

function mapGroups(items: Array<Record<string, unknown>>) {
  return items.flatMap((item) => {
    if (typeof item.group_id !== "string" || typeof item.name !== "string")
      return [];
    return [
      {
        id: item.group_id,
        name: item.name,
        color: typeof item.color === "string" ? item.color : "#1769e0",
        version: typeof item.version === "number" ? item.version : 1,
      },
    ];
  });
}

/** User/session changes must never display a previous user's cached projection. */
export function useClearPlannerProjection() {
  const queryClient = useQueryClient();
  return () => queryClient.removeQueries({ queryKey: plannerKeys.all });
}
