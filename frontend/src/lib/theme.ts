import { useEffect, useState } from "react";

export type Theme = "paper" | "terminal";

const STORAGE_KEY = "ainews.theme";

export function useTheme(defaultTheme: Theme = "paper"): [Theme, (t: Theme) => void, () => void] {
  const [theme, setThemeState] = useState<Theme>(() => {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === "paper" || stored === "terminal") return stored;
    } catch {
      /* no-op */
    }
    return defaultTheme;
  });

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      /* no-op */
    }
  }, [theme]);

  const setTheme = (next: Theme) => setThemeState(next);
  const toggle = () => setThemeState(theme === "paper" ? "terminal" : "paper");

  return [theme, setTheme, toggle];
}
