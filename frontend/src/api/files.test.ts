import { describe, expect, it } from "vitest";

import { mapFileRecord } from "./files";

describe("file API contracts", () => {
  it("keeps the file service identifier while converting presentation field names", () => {
    expect(
      mapFileRecord({
        id: 7,
        filename: "计划.md",
        file_size: 42,
        mime_type: "text/markdown",
        category: "document",
        folder_id: null,
        parse_status: "ready",
        file_url: "/media/7",
      }),
    ).toEqual({
      id: 7,
      filename: "计划.md",
      fileSize: 42,
      mimeType: "text/markdown",
      category: "document",
      folderId: null,
      parseStatus: "ready",
      fileUrl: "/media/7",
    });
  });
});
