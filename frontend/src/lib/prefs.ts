// Persisted user preferences (checklist N "Preferences window"). One
// localStorage key, "fv_prefs", is the source of truth for DEFAULTS; the
// Zustand store holds live-session values and seeds from here at init.
// loadPrefs() backfills from the older single-purpose keys (fv_theme,
// fv_tools_layout, fv_overlay) so existing users keep their settings.

export type ThemeChoice = "dark" | "light" | "system";
/** Swappable accent scheme (Preferences → Appearance → Color scheme). */
export type Accent = "violet" | "teal" | "ocean" | "amber" | "rose";
/** UI density — drives the spacing/row-height/font-size token block. */
export type Density = "compact" | "regular" | "comfy";

export interface Prefs {
  // ── Appearance ──
  theme: ThemeChoice;
  /** Accent ramp; tints selection/active chrome, surfaces stay neutral. */
  accent: Accent;
  /** Chrome density (compact | regular | comfy). */
  density: Density;
  defaultCmap: string;
  /** Default intensity transform for newly opened images. */
  defaultTransform: "linear" | "log" | "equalize";
  /** Open new images inverted (bright↔dark). */
  defaultInvert: boolean;
  /** Percentile auto-contrast window. */
  autoLoPct: number;
  autoHiPct: number;
  /** Auto-window new images that carry no embedded display range. */
  autoContrastOnOpen: boolean;

  // ── Tools & Layout ──
  /** Inspector tools layout: separate cards vs one unified browser. */
  toolsLayout: "cards" | "unified";
  minimap: boolean;
  /** Pixel-inspector grid dimension, odd. */
  inspectorGrid: number;

  // ── Measurement & Overlays ──
  overlayColor: string;
  overlaySize: "S" | "M" | "L" | "XL";
  overlayEndSymbol: "bar" | "none" | "circle" | "square" | "cross";
  /** ⊥ averaging width (px) for profile captures. */
  profileWidth: number;
  profileReduce: "mean" | "sum";
  scaleBarVisible: boolean;
  /** Scale-bar label font size (screen px). */
  scaleBarFontSize: number;

  // ── Export ──
  exportFormat: "png" | "tiff16" | "jpeg" | "svg" | "pdf";
  /** Default export resolution multiplier 1–4. */
  exportScale: number;
  exportScaleBar: boolean;
  exportMeasures: boolean;
  exportColorbar: boolean;

  // ── Advanced ──
  colorbarSide: "left" | "right";
  colorbarOnByDefault: boolean;
  fixedZoomW: number;
  fixedZoomH: number;
  /** Default tilt-correction geometry seeded onto newly opened images. */
  tiltGeometry: "cross-section" | "surface";
}

const KEY = "fv_prefs";

export const DEFAULTS: Prefs = {
  theme: "system",
  accent: "violet",
  density: "regular",
  defaultCmap: "gray",
  defaultTransform: "linear",
  defaultInvert: false,
  autoLoPct: 0.5,
  autoHiPct: 99.5,
  autoContrastOnOpen: false,
  toolsLayout: "cards",
  minimap: true,
  inspectorGrid: 7,
  overlayColor: "#ffffff",
  overlaySize: "M",
  overlayEndSymbol: "bar",
  profileWidth: 1,
  profileReduce: "mean",
  scaleBarVisible: true,
  scaleBarFontSize: 20,
  exportFormat: "png",
  exportScale: 1,
  exportScaleBar: true,
  exportMeasures: true,
  exportColorbar: false,
  colorbarSide: "right",
  colorbarOnByDefault: false,
  fixedZoomW: 256,
  fixedZoomH: 256,
  tiltGeometry: "cross-section",
};

/** Backfill from the older single-purpose keys for fields not yet present
 *  in fv_prefs — zero-loss migration for existing users. */
function legacyBackfill(): Partial<Prefs> {
  const out: Partial<Prefs> = {};
  const t = localStorage.getItem("fv_theme");
  if (t === "dark" || t === "light" || t === "system") out.theme = t;
  const tl = localStorage.getItem("fv_tools_layout");
  if (tl === "unified" || tl === "cards") out.toolsLayout = tl;
  try {
    const ov = JSON.parse(localStorage.getItem("fv_overlay") ?? "null") as {
      color?: string;
      size?: Prefs["overlaySize"];
      endSymbol?: Prefs["overlayEndSymbol"];
    } | null;
    if (ov && typeof ov === "object") {
      if (typeof ov.color === "string") out.overlayColor = ov.color;
      if (ov.size && ["S", "M", "L", "XL"].includes(ov.size))
        out.overlaySize = ov.size;
      if (ov.endSymbol) out.overlayEndSymbol = ov.endSymbol;
    }
  } catch {
    /* ignore malformed legacy overlay */
  }
  return out;
}

export function loadPrefs(): Prefs {
  let stored: Partial<Prefs> = {};
  try {
    stored = JSON.parse(localStorage.getItem(KEY) ?? "{}") as Partial<Prefs>;
  } catch {
    /* corrupt prefs → defaults */
  }
  // precedence: explicit stored value > legacy key > built-in default
  return { ...DEFAULTS, ...legacyBackfill(), ...stored };
}

export function savePrefs(p: Prefs): void {
  localStorage.setItem(KEY, JSON.stringify(p));
}
