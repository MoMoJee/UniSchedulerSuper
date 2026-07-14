import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference = "system" | "light" | "dark";

interface UiState {
  theme: ThemePreference;
  leftPanelOpen: boolean;
  agentPanelOpen: boolean;
  panelLayout: Record<string, number>;
  setTheme: (theme: ThemePreference) => void;
  setLeftPanelOpen: (open: boolean) => void;
  setAgentPanelOpen: (open: boolean) => void;
  setPanelLayout: (layout: Record<string, number>) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      leftPanelOpen: false,
      agentPanelOpen: false,
      panelLayout: { navigation: 22, workspace: 56, agent: 22 },
      setTheme: (theme) => set({ theme }),
      setLeftPanelOpen: (leftPanelOpen) => set({ leftPanelOpen }),
      setAgentPanelOpen: (agentPanelOpen) => set({ agentPanelOpen }),
      setPanelLayout: (panelLayout) => set({ panelLayout }),
    }),
    {
      name: "unischedulersuper-ui",
      partialize: (state) => ({
        theme: state.theme,
        panelLayout: state.panelLayout,
      }),
    },
  ),
);
