import { beforeEach, describe, expect, it } from "vitest";

import { useWorkbenchSurfaceStore } from "./workbench-surface-store";

describe("workbench surface store", () => {
  beforeEach(() =>
    useWorkbenchSurfaceStore.setState({
      surface: null,
      dialog: null,
      entityId: null,
    }),
  );

  it("keeps overlay state separate from domain data", () => {
    useWorkbenchSurfaceStore.getState().openSurface("files");
    useWorkbenchSurfaceStore.getState().openDialog("event", "event-1");
    expect(useWorkbenchSurfaceStore.getState()).toMatchObject({
      surface: "files",
      dialog: "event",
      entityId: "event-1",
    });
    useWorkbenchSurfaceStore.getState().closeSurface();
    expect(useWorkbenchSurfaceStore.getState().surface).toBeNull();
    expect(useWorkbenchSurfaceStore.getState().dialog).toBe("event");
  });

  it("hydrates from URL-compatible values", () => {
    useWorkbenchSurfaceStore.getState().hydrate("settings", null, null);
    expect(useWorkbenchSurfaceStore.getState().surface).toBe("settings");
  });
});
