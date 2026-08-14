import { useEffect, useState } from "react";
import {
  applyResolvedTheme,
  persistThemeMode,
  prefersDarkScheme,
  readStoredThemeMode,
  resolveTheme,
  type ThemeMode,
} from "./theme";

export function useTheme() {
  const [mode, setModeState] = useState<ThemeMode>(readStoredThemeMode);
  const [prefersDark, setPrefersDark] = useState(prefersDarkScheme);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => setPrefersDark(media.matches);
    media.addEventListener("change", onChange);
    return () => media.removeEventListener("change", onChange);
  }, []);

  const resolved = resolveTheme(mode, prefersDark);

  useEffect(() => {
    applyResolvedTheme(resolved, document.documentElement);
  }, [resolved]);

  function setMode(next: ThemeMode) {
    setModeState(next);
    persistThemeMode(next);
  }

  return { mode, resolved, setMode };
}
