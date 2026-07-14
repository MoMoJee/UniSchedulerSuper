import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./errors";

export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: (failureCount, error) =>
          !(
            error instanceof ApiError &&
            [401, 403, 409, 410, 422, 423].includes(error.status)
          ) && failureCount < 2,
        staleTime: 30_000,
        refetchOnWindowFocus: false,
      },
      mutations: { retry: false },
    },
  });
}
