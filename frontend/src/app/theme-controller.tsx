import { useEffect } from "react";

import { useUiStore } from "../stores/ui-store";
import { settingsApi } from "../api/settings";

export function ThemeController() {
  const theme = useUiStore((state) => state.theme);
  const goldTheme = useUiStore((state) => state.goldTheme);
  const setTheme = useUiStore((state) => state.setTheme);
  const setGoldTheme = useUiStore((state) => state.setGoldTheme);

  useEffect(() => {
    let active = true;
    void settingsApi
      .getPreferences()
      .then((preferences) => {
        if (!active) return;
        if (typeof preferences.theme === "string")
          setTheme(preferences.theme as Parameters<typeof setTheme>[0]);
        setGoldTheme(preferences.use_gold_theme === true);
      })
      .catch(() => undefined);
    return () => {
      active = false;
    };
  }, [setGoldTheme, setTheme]);

  useEffect(() => {
    const root = document.documentElement;
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const apply = () => {
      const resolved =
        theme === "system" ? (media?.matches ? "dark" : "light") : theme;
      root.dataset.theme = resolved;
    };
    apply();
    // “跟随系统”不是仅在首次加载取一次值；系统配色改变后立即更新。
    if (theme !== "system" || !media) return undefined;
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  useEffect(() => {
    document.documentElement.toggleAttribute("data-gold", goldTheme);
  }, [goldTheme]);

  return null;
}
