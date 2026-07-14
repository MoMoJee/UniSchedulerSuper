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
      const [
        events,
        eventDefinitions,
        reminders,
        reminderDefinitions,
        groups,
        shared,
      ] = await Promise.all([
        plannerApi.listEventOccurrences(from, to, signal),
        plannerApi.listEventDefinitions(from, to, signal),
        plannerApi.listReminders(from, to, signal),
        plannerApi.listReminders(undefined, undefined, signal),
        plannerApi.listGroups(signal),
        shareGroupId
          ? plannerApi.listSharedOccurrences(shareGroupId, from, to, signal)
          : Promise.resolve(null),
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
        occurrences: [
          ...(events.occurrences ?? []),
          ...(shared?.occurrences ?? []),
        ].map((value) => withDefinitionRule(value, eventRules)),
        reminders: (reminders.occurrences ?? []).map((value) =>
          withDefinitionRule(value, reminderRules),
        ),
        groups: (groups.groups ?? []).flatMap((item) => {
          if (
            typeof item.group_id !== "string" ||
            typeof item.name !== "string"
          )
            return [];
          return [
            {
              id: item.group_id,
              name: item.name,
              color: typeof item.color === "string" ? item.color : "#1769e0",
              version: typeof item.version === "number" ? item.version : 1,
            },
          ];
        }),
      };
    },
    staleTime: 0,
  });
}

/** User/session changes must never display a previous user's cached projection. */
export function useClearPlannerProjection() {
  const queryClient = useQueryClient();
  return () => queryClient.removeQueries({ queryKey: plannerKeys.all });
}
