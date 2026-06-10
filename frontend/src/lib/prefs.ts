// Persisted user preferences (checklist N "Preferences dialog").

export interface Prefs {
  defaultCmap: string;
  profileWidth: number;
  minimap: boolean;
  /** Percentile auto-contrast window (D13). */
  autoLoPct: number;
  autoHiPct: number;
  /** Default export resolution multiplier 1–4 (D13). */
  exportScale: number;
  /** Pixel-inspector grid dimension, odd (D13). */
  inspectorGrid: number;
}

const KEY = "fv_prefs";

const DEFAULTS: Prefs = {
  defaultCmap: "gray",
  profileWidth: 1,
  minimap: true,
  autoLoPct: 0.5,
  autoHiPct: 99.5,
  exportScale: 1,
  inspectorGrid: 7,
};

export function loadPrefs(): Prefs {
  try {
    return {
      ...DEFAULTS,
      ...(JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>),
    };
  } catch {
    return { ...DEFAULTS };
  }
}

export function savePrefs(p: Prefs): void {
  localStorage.setItem(KEY, JSON.stringify(p));
}
