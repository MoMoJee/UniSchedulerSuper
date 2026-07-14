import { useEffect } from "react";

import { useUiStore } from "../stores/ui-store";

export function ThemeController() {
  const theme = useUiStore((state) => state.theme);

  useEffect(() => {
    const root = document.documentElement;
    const prefersDark =
      window.matchMedia?.("(prefers-color-scheme: dark)").matches ?? false;
    const resolved =
      theme === "system" ? (prefersDark ? "dark" : "light") : theme;
    root.dataset.theme = resolved;
  }, [theme]);

  return null;
}
