import { describe, expect, it } from "vitest";

import { ApiError } from "./errors";
import { createQueryClient } from "./queryClient";

describe("QueryClient retry policy", () => {
  it("does not retry deliberate authorization, conflict, archive, validation, or lock responses", () => {
    const retry = createQueryClient().getDefaultOptions().queries?.retry;
    if (typeof retry !== "function")
      throw new Error("Expected a query retry function.");
    for (const status of [401, 403, 409, 410, 422, 423]) {
      expect(
        retry(
          0,
          new ApiError({
            message: "x",
            status,
            code: null,
            details: null,
            method: "GET",
            url: "/x",
          }),
        ),
      ).toBe(false);
    }
  });
});
