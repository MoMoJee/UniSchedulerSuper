import { queryOptions } from "@tanstack/react-query";

import { readFrontendBootstrap } from "../bootstrap";
import { plannerApi } from "./planner";
import { plannerKeys } from "./queryKeys";

export function plannerBootstrapQuery() {
  const username = readFrontendBootstrap().user.username;
  return queryOptions({
    queryKey: plannerKeys.bootstrap(username),
    queryFn: () => plannerApi.bootstrap(),
  });
}

export function plannerCalendarQuery(
  from: string,
  to: string,
  filters: Record<string, string>,
) {
  const username = readFrontendBootstrap().user.username;
  return queryOptions({
    queryKey: plannerKeys.calendar(username, from, to, filters),
    queryFn: ({ signal }) => plannerApi.listEventOccurrences(from, to, signal),
  });
}
