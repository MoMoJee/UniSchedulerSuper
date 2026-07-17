import { create } from "zustand";

export type WorkbenchSurface = "search" | "settings" | "files" | "share" | null;

interface WorkbenchSurfaceState {
  surface: WorkbenchSurface;
  dialog: string | null;
  entityId: string | null;
  openSurface: (surface: Exclude<WorkbenchSurface, null>) => void;
  closeSurface: () => void;
  openDialog: (dialog: string, entityId?: string | null) => void;
  closeDialog: () => void;
  hydrate: (
    surface: WorkbenchSurface,
    dialog: string | null,
    entityId: string | null,
  ) => void;
}

export const useWorkbenchSurfaceStore = create<WorkbenchSurfaceState>(
  (set) => ({
    surface: null,
    dialog: null,
    entityId: null,
    openSurface: (surface) => set({ surface }),
    closeSurface: () => set({ surface: null }),
    openDialog: (dialog, entityId = null) => set({ dialog, entityId }),
    closeDialog: () => set({ dialog: null, entityId: null }),
    hydrate: (surface, dialog, entityId) => set({ surface, dialog, entityId }),
  }),
);

export const WORKBENCH_SURFACES = new Set([
  "search",
  "settings",
  "files",
  "share",
]);
