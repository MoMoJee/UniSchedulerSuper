import { useEffect } from "react";

import { useUiStore } from "../stores/ui-store";

export function ThemeController() {
  const theme = useUiStore((state) => state.theme);

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

  return null;
}
