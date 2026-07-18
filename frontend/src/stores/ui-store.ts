import { create } from "zustand";
import { persist } from "zustand/middleware";

export type ThemePreference =
  | "system"
  | "light"
  | "dark"
  | "china-red"
  | "warm-pastel"
  | "cool-pastel"
  | "macaron"
  | "dopamine"
  | "forest"
  | "sunset"
  | "ocean"
  | "sakura"
  | "cyberpunk";

interface UiState {
  theme: ThemePreference;
  goldTheme: boolean;
  leftPanelOpen: boolean;
  agentPanelOpen: boolean;
  panelLayout: Record<string, number>;
  setTheme: (theme: ThemePreference) => void;
  setGoldTheme: (enabled: boolean) => void;
  setLeftPanelOpen: (open: boolean) => void;
  setAgentPanelOpen: (open: boolean) => void;
  setPanelLayout: (layout: Record<string, number>) => void;
}

export const useUiStore = create<UiState>()(
  persist(
    (set) => ({
      theme: "system",
      goldTheme: false,
      leftPanelOpen: false,
      agentPanelOpen: false,
      // 与旧版固定工作台一致：导航 / 内容 / Agent = 20 / 50 / 30。
      panelLayout: { navigation: 20, workspace: 50, agent: 30 },
      setTheme: (theme) => set({ theme }),
      setGoldTheme: (goldTheme) => set({ goldTheme }),
      setLeftPanelOpen: (leftPanelOpen) => set({ leftPanelOpen }),
      setAgentPanelOpen: (agentPanelOpen) => set({ agentPanelOpen }),
      setPanelLayout: (panelLayout) => set({ panelLayout }),
    }),
    {
      name: "unischedulersuper-ui",
      version: 3,
      migrate: (persisted, version) => {
        const state = persisted as Partial<UiState>;
        const layout = state.panelLayout;
        // 只升级 FR 初版写入的错误默认比例；用户实际拖拽后的比例原样保留。
        // R0–R5 changes the canonical desktop composition. Migrate every
        // pre-R5 layout once so stale experimental widths cannot hide the
        // calendar or Agent; later user resizing remains persistent.
        const panelLayout =
          version < 3
            ? { navigation: 20, workspace: 50, agent: 30 }
            : (layout ?? { navigation: 20, workspace: 50, agent: 30 });
        return {
          theme: state.theme ?? "system",
          goldTheme: state.goldTheme ?? false,
          panelLayout,
        };
      },
      partialize: (state) => ({
        theme: state.theme,
        goldTheme: state.goldTheme,
        panelLayout: state.panelLayout,
      }),
    },
  ),
);
