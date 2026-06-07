// Persisted user preferences (checklist N "Preferences dialog").

export interface Prefs {
  defaultCmap: string;
  profileWidth: number;
  minimap: boolean;
}

const KEY = "fv_prefs";

const DEFAULTS: Prefs = {
  defaultCmap: "gray",
  profileWidth: 1,
  minimap: true,
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
