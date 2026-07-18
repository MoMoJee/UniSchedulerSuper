import { apiClient, type JsonObject } from "./http";

export interface UserPreferences extends JsonObject {
  theme?: string;
  calendar_view_default?: string;
  show_week_number?: boolean;
  reminder_enabled?: boolean;
  reminder_sound?: boolean;
  ai_enabled?: boolean;
  ai_auto_suggest?: boolean;
  default_event_duration?: number;
  use_gold_theme?: boolean;
  week_number_periods?: Array<{
    name: string;
    year?: number;
    month: number;
    day: number;
  }>;
}

export const settingsApi = {
  getPreferences: () =>
    apiClient.request<UserPreferences>("/get_calendar/user_settings/"),
  savePreferences: (preferences: UserPreferences) =>
    apiClient.request<JsonObject>("/get_calendar/user_settings/", {
      method: "POST",
      body: preferences,
    }),
  getAgentConfig: () => apiClient.request<JsonObject>("/api/agent/config/"),
  updateModel: (body: JsonObject) =>
    apiClient.request<JsonObject>("/api/agent/model-config/update/", {
      method: "POST",
      body,
    }),
  updateOptimization: (body: JsonObject) =>
    apiClient.request<JsonObject>("/api/agent/optimization-config/update/", {
      method: "POST",
      body,
    }),
  getTokenUsage: () => apiClient.request<JsonObject>("/api/agent/token-usage/"),
  getSkills: () =>
    apiClient.request<{ items: JsonObject[] }>("/api/agent/skills/"),
  toggleSkill: (id: number) =>
    apiClient.request<JsonObject>(`/api/agent/skills/${id}/toggle/`, {
      method: "POST",
      body: {},
    }),
  importSkill: (name: string, description: string, content: string) =>
    apiClient.request<JsonObject>("/api/agent/skills/import/", {
      method: "POST",
      body: { name, description, content },
    }),
  semesters: () =>
    apiClient.request<{
      semesters: Array<{ code: string; name: string; current: boolean }>;
      current_semester: string;
    }>("/api/import/semesters/"),
  fetchCourses: (cookie: string, semester: string) =>
    apiClient.request<{ courses: JsonObject[]; semester: JsonObject }>(
      "/api/import/fetch/",
      { method: "POST", body: { cookie, semester } },
    ),
  confirmCourses: (courses: JsonObject[]) =>
    apiClient.request<{
      status: string;
      imported_count: number;
      skipped_count?: number;
      message: string;
    }>("/api/import/confirm/", { method: "POST", body: { courses } }),
};
