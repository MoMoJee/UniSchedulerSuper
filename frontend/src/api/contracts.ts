/**
 * Stable wire contracts verified against core/planner/presentation.py and
 * core/planner/entities.py. Components consume the mapped camelCase models,
 * never these snake_case DTOs directly.
 */
export interface RecurrenceWire {
  series_id: string;
  rrule: string;
  tzid: string;
  source_version: number;
}

export interface EventDefinitionWire {
  entity_type: "event";
  event_id: string;
  version: number;
  title: string;
  description: string;
  location: string;
  status: string;
  importance: string;
  urgency: string;
  group_id: string | null;
  is_all_day: boolean;
  start: string;
  end: string | null;
  recurrence:
    | (RecurrenceWire & {
        dtstart: string;
        rdates: string[];
        exdates: string[];
        override_count: number;
      })
    | null;
}

export interface TodoWire {
  entity_type: "todo";
  todo_id: string;
  version: number;
  title: string;
  description: string;
  status: string;
  importance: string;
  urgency: string;
  priority_score: number;
  estimated_duration_seconds: number | null;
  group_id: string | null;
  due: string | null;
  tags: string[];
  dependencies: string[];
  converted_to_event_id: string | null;
}

export interface ReminderWire {
  entity_type: "reminder";
  reminder_id: string;
  version: number;
  title: string;
  content: string;
  priority: string;
  status: string;
  tzid: string;
  trigger: string | null;
  snooze_until: string | null;
  notification_sent_at: string | null;
  recurrence: RecurrenceWire | null;
}

export interface GroupWire {
  group_id: string;
  version: number;
  name: string;
  description: string;
  color: string;
  group_type: string;
  default_importance: string;
  default_urgency: string;
}

export interface ShareGroupWire {
  share_group_id: string;
  name: string;
  description: string;
  color: string;
  owner_id: number;
  read_only: boolean;
}

export interface SearchResultWire {
  type: "event" | "todo" | "reminder";
  entity_id: string;
  title: string;
  source_version: number;
}

export interface QuickActionTaskWire {
  task_id: string;
  status: string;
  status_url: string;
  created_at: string;
  input_type: "text" | "audio";
}

export interface PlannerEntitySummary {
  id: string;
  version: number;
  title: string;
  entityType: "event" | "todo" | "reminder";
}

export function mapPlannerEntitySummary(
  value: EventDefinitionWire | TodoWire | ReminderWire,
): PlannerEntitySummary {
  if (value.entity_type === "event")
    return {
      id: value.event_id,
      version: value.version,
      title: value.title,
      entityType: "event",
    };
  if (value.entity_type === "todo")
    return {
      id: value.todo_id,
      version: value.version,
      title: value.title,
      entityType: "todo",
    };
  return {
    id: value.reminder_id,
    version: value.version,
    title: value.title,
    entityType: "reminder",
  };
}
