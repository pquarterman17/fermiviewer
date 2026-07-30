// Per-element display colours for the EDS workspace. One registry drives every
// place an element is drawn — composite channels, the single-element map tint,
// and the spectrum's characteristic-line labels — so "Carbon is green" holds
// everywhere and survives a reload.
//
// Resolution order for a symbol: user override (localStorage) → curated colour
// → golden-angle hue keyed on the element's position in the periodic table.
// The old index-into-a-palette assignment is gone: it made a channel's colour
// depend on the order elements were added, so the same element changed colour
// between a Quantify run and an Explore pick.

import { useMemo, useSyncExternalStore } from "react";

import { ALL_ELEMENTS } from "./periodicTable";

const STORAGE_KEY = "fv_eds_element_colors";
const HEX = /^#[0-9a-f]{6}$/i;

/** Classic EDS overlay palette, offered as one-click swatches in the picker. */
export const EDS_PALETTE = [
  "#f43f5e", // red
  "#22c55e", // green
  "#3b82f6", // blue
  "#eab308", // yellow
  "#a855f7", // purple
  "#06b6d4", // cyan
  "#f97316", // orange
  "#ec4899", // pink
];

/** Colours for the elements EDS users overlay most often, picked so the
 *  common systems (Si/Al/O, Fe/Cr/Ni, Ga/As/N) stay legible side by side. */
const CURATED: Readonly<Record<string, string>> = {
  C: "#22c55e",
  N: "#06b6d4",
  O: "#3b82f6",
  F: "#22d3ee",
  Na: "#a855f7",
  Mg: "#84cc16",
  Al: "#f97316",
  Si: "#eab308",
  P: "#fb923c",
  S: "#facc15",
  Cl: "#4ade80",
  K: "#c084fc",
  Ca: "#94a3b8",
  Ti: "#64748b",
  Cr: "#10b981",
  Mn: "#d4d4d4",
  Fe: "#f43f5e",
  Co: "#6366f1",
  Ni: "#14b8a6",
  Cu: "#ea580c",
  Zn: "#7c3aed",
  Ga: "#ec4899",
  Ge: "#8b5cf6",
  As: "#a3e635",
  Mo: "#0ea5e9",
  Ag: "#cbd5e1",
  Sn: "#f59e0b",
  W: "#a8a29e",
  Pt: "#e2e8f0",
  Au: "#fbbf24",
  Pb: "#9ca3af",
};

function hslHex(hue: number, sat: number, light: number): string {
  const chroma = (1 - Math.abs(2 * light - 1)) * sat;
  const second = chroma * (1 - Math.abs(((hue / 60) % 2) - 1));
  const base = light - chroma / 2;
  const sector = Math.floor(hue / 60) % 6;
  const rgb = [
    [chroma, second, 0],
    [second, chroma, 0],
    [0, chroma, second],
    [0, second, chroma],
    [second, 0, chroma],
    [chroma, 0, second],
  ][sector];
  return `#${rgb
    .map((c) =>
      Math.round((c + base) * 255)
        .toString(16)
        .padStart(2, "0"),
    )
    .join("")}`;
}

/** Deterministic distinct hue for elements outside the curated table. The
 *  golden angle over table position keeps neighbouring elements far apart in
 *  hue, which is exactly the case where two channels get confused. */
function fallbackColor(symbol: string): string {
  const index = ALL_ELEMENTS.indexOf(symbol);
  const seed = index >= 0 ? index : symbol.charCodeAt(0);
  return hslHex((seed * 137.508) % 360, 0.68, 0.56);
}

/** The colour an element uses when the user has not overridden it. */
export function defaultElementColor(symbol: string): string {
  return CURATED[symbol] ?? fallbackColor(symbol);
}

function load(): Readonly<Record<string, string>> {
  try {
    const raw: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    if (!raw || typeof raw !== "object") return {};
    const clean: Record<string, string> = {};
    for (const [symbol, value] of Object.entries(raw)) {
      if (typeof value === "string" && HEX.test(value)) clean[symbol] = value;
    }
    return Object.freeze(clean);
  } catch {
    return Object.freeze({});
  }
}

let overrides: Readonly<Record<string, string>> = load();
const listeners = new Set<() => void>();

function commit(next: Record<string, string>) {
  overrides = Object.freeze(next);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides));
  } catch {
    // A full or blocked quota must not break the in-session colour change.
  }
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Resolved display colour for an element (override → curated → hue). */
export function elementColor(symbol: string): string {
  return overrides[symbol] ?? defaultElementColor(symbol);
}

/** Pin an element to a colour everywhere. Ignores anything but #rrggbb. */
export function setElementColor(symbol: string, hex: string): void {
  if (!HEX.test(hex) || overrides[symbol] === hex) return;
  commit({ ...overrides, [symbol]: hex });
}

/** Drop one element's override, restoring its curated/hue default. */
export function resetElementColor(symbol: string): void {
  if (!(symbol in overrides)) return;
  const next = { ...overrides };
  delete next[symbol];
  commit(next);
}

/** Drop every override — the "restore default colours" action. */
export function resetAllElementColors(): void {
  if (Object.keys(overrides).length === 0) return;
  commit({});
}

/** True when the element's colour is a user override rather than a default. */
export function isElementColorCustom(symbol: string): boolean {
  return symbol in overrides;
}

/**
 * Reactive colour resolver. The returned function's identity changes only when
 * some element's colour changes, so callers can list it in a `useMemo` /
 * `useEffect` dependency array and re-render exactly on a recolour.
 */
export function useElementColors(): (symbol: string) => string {
  const current = useSyncExternalStore(
    subscribe,
    () => overrides,
    () => overrides,
  );
  return useMemo(
    () => (symbol: string) => current[symbol] ?? defaultElementColor(symbol),
    [current],
  );
}

/** One element's colour, re-rendering the caller when it is recoloured. */
export function useElementColor(symbol: string): string {
  return useElementColors()(symbol);
}

function hexToRgb(hex: string): [number, number, number] {
  const value = HEX.test(hex) ? hex : "#888888";
  return [1, 3, 5].map((i) => parseInt(value.slice(i, i + 2), 16)) as [
    number,
    number,
    number,
  ];
}

/**
 * 256×RGBA8 ramp from black through the element's colour to near-white, for
 * tinting a single-element map the same colour that element wears in the
 * composite. The white shoulder above t≈0.82 keeps the hottest pixels
 * distinguishable — a flat black→colour ramp saturates and loses them.
 */
export function buildElementLut(hex: string): Uint8Array {
  const [r, g, b] = hexToRgb(hex);
  const out = new Uint8Array(256 * 4);
  const knee = 0.82;
  for (let i = 0; i < 256; i++) {
    const t = i / 255;
    const [cr, cg, cb] =
      t <= knee
        ? [r, g, b].map((c) => (c * t) / knee)
        : [r, g, b].map((c) => c + (255 - c) * ((t - knee) / (1 - knee)));
    out[i * 4] = Math.round(cr);
    out[i * 4 + 1] = Math.round(cg);
    out[i * 4 + 2] = Math.round(cb);
    out[i * 4 + 3] = 255;
  }
  return out;
}
