import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";

import { loadPrefs, type Prefs } from "../../lib/prefs";
import {
  useAppearancePreviewState,
  type AppearancePreview,
} from "../../store/appearancePreview";

type Appearance = Pick<Prefs, "theme" | "accent" | "density">;
type AppearanceKey = keyof Appearance;

function appearance(prefs: Prefs): Appearance {
  return {
    theme: prefs.theme,
    accent: prefs.accent,
    density: prefs.density,
  };
}

function resolveAppearance(prefs: Appearance): AppearancePreview {
  const theme = prefs.theme === "system"
    ? window.matchMedia?.("(prefers-color-scheme: light)").matches
      ? "light"
      : "dark"
    : prefs.theme;
  return { theme, accent: prefs.accent, density: prefs.density };
}

function applyAppearance(prefs: Appearance): void {
  const resolved = resolveAppearance(prefs);
  document.documentElement.setAttribute("data-theme", resolved.theme);
  document.documentElement.setAttribute("data-accent", resolved.accent);
  document.documentElement.setAttribute("data-density", resolved.density);
  useAppearancePreviewState.getState().setPreview(resolved);
}

function clearPreview(): void {
  useAppearancePreviewState.getState().setPreview(null);
}

/** Preview appearance through DOM tokens + an ephemeral, non-persisted store. */
export function useAppearancePreview(
  open: boolean,
  setOpen: (open: boolean) => void,
  prefs: Prefs,
  setPrefs: Dispatch<SetStateAction<Prefs>>,
) {
  const original = useRef<Appearance | null>(null);

  useEffect(() => {
    if (!open) return;
    clearPreview();
    original.current = appearance(loadPrefs());
    return () => {
      if (original.current) applyAppearance(original.current);
      clearPreview();
    };
  }, [open]);

  // Compute, set, then apply — never touch the DOM inside a state updater.
  // React double-invokes updaters in StrictMode and may replay them under
  // concurrent rendering. previewAll below already has the right shape.
  const preview = <K extends AppearanceKey>(key: K, value: Appearance[K]) => {
    const next = { ...prefs, [key]: value };
    setPrefs(next);
    applyAppearance(appearance(next));
  };

  const previewAll = (next: Prefs) => {
    setPrefs(next);
    applyAppearance(appearance(next));
  };

  const cancel = () => {
    if (original.current) applyAppearance(original.current);
    original.current = null;
    clearPreview();
    setOpen(false);
  };

  const commit = () => {
    original.current = null;
    clearPreview();
  };

  return { preview, previewAll, cancel, commit };
}
