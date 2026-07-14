import { describe, expect, it } from "vitest";

import { ApiError, toUserFacingApiMessage } from "./errors";

describe("API error presentation", () => {
  for (const [status, expected] of [
    [401, "登录已失效"],
    [403, "没有执行此操作的权限"],
    [409, "数据已被其他操作更新"],
    [410, "已封存"],
    [422, "输入内容不符合"],
    [423, "隔离或锁定"],
  ]) {
    it(`maps ${status} to a distinct safe message`, () => {
      const error = new ApiError({
        message: "server",
        status: Number(status),
        code: null,
        details: null,
        method: "PATCH",
        url: "/api/v2/events/1/",
      });
      expect(toUserFacingApiMessage(error)).toContain(expected);
    });
  }
});
