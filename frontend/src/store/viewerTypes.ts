// Pure types, constants and label helpers for the viewer store — split
// from viewer.ts (repo-health #33). No zustand, no localStorage, no DOM:
// everything here is importable from anywhere without side effects.

import type { ImageMeta } from "../lib/api";
import type { ColormapName } from "../lib/colormaps";

/** Per-image view: z = screen px per image px (1 → 100 %),
 *  (px, py) = normalized image point under the viewport centre. */
export interface View {
  z: number;
  px: number;
  py: number;
}

/** Per-image display: lo/hi normalized [0,1] against image min/max. */
export type DisplayTransform = "linear" | "log" | "equalize";

export interface Display {
  lo: number;
  hi: number;
  gamma: number;
  cmap: ColormapName;
  invert: boolean;
  /** intensity transform applied to the texture before window/γ/LUT */
  transform: DisplayTransform;
  /** colorbar tick interval in real value units (nm for AFM); 0/undefined = auto */
  tickStep?: number;
  /** colorbar tick count (overrides tickStep when set and > 0) */
  tickCount?: number;
  /** colorbar tick-label font size in screen px; undefined = 11 (default) */
  tickFontSize?: number;
}

export type ColorbarSide = "left" | "right" | "bottom";

export const DEFAULT_DISPLAY: Display = {
  lo: 0,
  hi: 1,
  gamma: 1,
  cmap: "gray",
  invert: false,
  transform: "linear",
};

/** One entry in an image's non-destructive edit history (design WS4d).
 *  Each step snapshots the FULL display state after the change, so a
 *  revert is just restoring that snapshot. `field` groups consecutive
 *  edits of the same control (a gamma drag coalesces into one step). */
export interface HistoryStep {
  id: number;
  label: string;
  field: string;
  display: Display;
}

/** Human label + coalescing field for a display change. Single-field
 *  patches get a specific label; the auto-window {lo,hi} pair and the
 *  reset patch are recognised so the card reads like the design example
 *  (Opened → Colormap → Auto contrast → Gamma). */
export function describePatch(
  patch: Partial<Display>,
): { field: string; label: string } {
  const keys = Object.keys(patch);
  const has = (k: keyof Display) => k in patch;
  if (keys.length === 2 && has("lo") && has("hi"))
    return { field: "window", label: "Auto contrast" };
  if (keys.length > 1) return { field: "reset", label: "Reset display" };
  if (has("cmap")) return { field: "cmap", label: `Colormap → ${patch.cmap}` };
  if (has("gamma"))
    return { field: "gamma", label: `Gamma ${(patch.gamma ?? 1).toFixed(2)}` };
  if (has("invert"))
    return { field: "invert", label: `Invert ${patch.invert ? "on" : "off"}` };
  if (has("transform"))
    return { field: "transform", label: `Transform → ${patch.transform}` };
  if (has("tickStep")) return { field: "tickStep", label: "Tick step" };
  if (has("tickCount")) return { field: "tickCount", label: "Tick count" };
  if (has("tickFontSize")) return { field: "tickFontSize", label: "Tick font" };
  if (has("lo") || has("hi")) return { field: "window", label: "Contrast" };
  return { field: "adjust", label: "Adjust" };
}

/** One entry in the named-ROI list (ROI Manager, audit Tier-2 #5).
 *  Geometry is stored as normalized pts (same as Measure.pts) + the
 *  original MeasureKind so recall can re-create either roi or ellipse. */
export interface SavedRoi {
  id: string;
  name: string;
  kind: "roi" | "ellipse";
  pts: { x: number; y: number }[];
  /** ISO timestamp — shown in the manager list for provenance */
  createdAt: string;
}

export type MeasureKind =
  | "distance"
  | "profile"
  | "angle"
  | "roi"
  | "ellipse"
  | "polyline"
  // closed area kinds (plan item 14): polygon is click-to-place vertices
  // closed by clicking vertex 0 again or double-click; lasso is a
  // freehand drag. Both share polygonStats/areaPxToPhysical (lib/geometry,
  // item 12) for their area label — never baked into exported figures
  // (W3 design; calc/export.py's measure_annotations skips any kind it
  // doesn't recognize, which for these two is intentional).
  | "polygon"
  | "lasso"
  // annotations (checklist H) — ride the measure rails: overlay
  // rendering, persistence, undo and export baking all come free
  | "text"
  | "arrow"
  | "box"
  | "circle";

export type EndSymbol = "bar" | "circle" | "cross" | "square" | "none";

/** Normalized 0–1 image coords survive derived images of the same aspect. */
export interface Measure {
  id: string;
  kind: MeasureKind;
  pts: { x: number; y: number }[];
  /** Enclosed holes subtracted from this region's area (plan item 19).
   *  Each inner array is one hole's closed ring, same normalized 0-1,
   *  implicitly-closed convention as `pts`. Only meaningful for the
   *  area-bearing kinds (polygon/lasso); absent or empty means "no
   *  holes" and is byte-identical to pre-#19 behaviour — chosen over a
   *  separate "hole" measure kind linked by geometric containment so a
   *  single-ring region's area math never has to change shape to stay
   *  correct (see lib/geometry.ts polygonStatsWithHoles). There is
   *  currently no drawing gesture that populates this field — see
   *  PROJECT_WORKFLOW_PLAN.md item 19's completion note for the
   *  reachability gap and the schema change persistence would need. */
  holes?: { x: number; y: number }[][];
  /** annotation caption (text / arrow / box kinds) */
  text?: string;
  /** per-item colour override (falls back to the overlay style) */
  color?: string;
  /** dragged label offset in screen px (from the default anchor) */
  labelDx?: number;
  labelDy?: number;
  /** endpoint glyph override (falls back to overlay style default) */
  endSymbol?: EndSymbol;
  /** ⊥ averaging width in image px; falls back to global profileWidth. */
  width?: number;
  /** Per-annotation screen px; undefined uses global, clamped to [6, 120]. */
  fontSize?: number;
}

/** Undoable mutations (Edit menu / ⌘Z). Derived-image entries remove
 *  only the CLIENT registration — the server keeps the DataStruct for
 *  the session, which is what makes redo instant and lossless. */
export type UndoEntry =
  | { t: "measure-add"; imageId: string; measure: Measure }
  | { t: "measure-del"; imageId: string; measure: Measure }
  | {
      t: "measure-move";
      imageId: string;
      measureId: string;
      before: Measure["pts"];
      after: Measure["pts"];
    }
  // Draw-a-hole (plan item 4): converting a top-level polygon/lasso ring
  // into a subtracted hole of `hostId`, or the reverse. `child` is the
  // FULL ring measure — carried whole (not just its pts) so undo restores
  // it with its original id/color/text intact, symmetric with how
  // measure-add/measure-del round-trip the whole Measure.
  | { t: "hole-add"; imageId: string; hostId: string; child: Measure }
  | { t: "hole-remove"; imageId: string; hostId: string; child: Measure }
  | { t: "derived"; meta: ImageMeta; parentId: string };

export function undoLabel(e: UndoEntry): string {
  switch (e.t) {
    case "measure-add":
      return `add ${e.measure.kind}`;
    case "measure-del":
      return `delete ${e.measure.kind}`;
    case "measure-move":
      return "move measure";
    case "hole-add":
      return "mark as hole";
    case "hole-remove":
      return "remove hole";
    case "derived":
      return e.meta.name;
  }
}

export const UNDO_CAP = 99;

export interface OverlayStyle {
  size: "XS" | "S" | "M" | "L" | "XL" | "XXL";
  color: string;
  /** Measurement/annotation line thickness in screen px (non-selected). */
  lineWidth: number;
  endSymbol: EndSymbol;
}

/** On-screen label px for each overlay size bucket. Shared by the
 *  MeasureOverlay renderer AND the export pipeline so burned-in labels
 *  match what's on the stage. */
export const OVERLAY_FONT_PX: Record<OverlayStyle["size"], number> = {
  XS: 10,
  S: 13,
  M: 16,
  L: 20,
  XL: 26,
  XXL: 34,
};

/** Per-image scale bar display overrides.
 *  x/y are fractional positions 0–1 relative to the stage viewport
 *  (default bottom-left ≈ 0.02, 0.92).
 *  lengthPhys null means auto (nice-number); thickness/fontSize null = auto. */
export interface ScaleBarState {
  x: number;          // normalized stage x (0 = left, 1 = right)
  y: number;          // normalized stage y (0 = top, 1 = bottom)
  lengthPhys: number | null;  // physical length override (in pixel_unit)
  thickness: number | null;   // bar thickness in screen px (null = auto)
  fontSize: number | null;    // label font size in px (null = auto)
  color: string | null;       // bar + label colour; null = "#ffffff" (audit #10)
  unitOverride: string | null; // force a display unit; null = auto (audit #10)
}

export type CaptureMode =
  | "none"
  | "zoom"
  | "fixed-zoom"
  | "box-profile"
  | "crop-save"
  | "calibrate"
  | "specnav" // click/drag the main image → drives the EELS/EDS spectrum
  | "fourdnav" // click/drag the main image → moves the 4D-STEM probe (#14)
  | MeasureKind;
export type Theme = "dark" | "light";
/** Swappable accent scheme (kept in sync with lib/prefs Accent; no import
 *  to avoid an init-time cycle, same as Theme vs ThemeChoice). */
export type Accent = "violet" | "teal" | "ocean" | "amber" | "rose";
/** UI density — drives the spacing/row-height/font-size token block. */
export type Density = "compact" | "regular" | "comfy";
export type ListView = "thumbs" | "names";
export type CompareMode = "split" | "flicker" | "subtract" | "sidebyside";
export type SelectGesture = "single" | "toggle" | "range";
/** Detected layer interfaces, surfaced on the stage by LayersOverlay. */
export interface LayersOverlayState {
  imageId: string;
  axis: "y" | "x";
  interfaces: number[];              // depth positions (image pixels)
  traces: (number[] | null)[];
  lateralOffset?: number;
  lateralRange?: [number, number];
  depthRange?: [number, number];
}

export type ToolKind =
  | "eels"
  | "eds"
  | "diffraction"
  | "fftmask"
  | "pixels"
  | "structure"
  | "overlay"
  | "surface" | "roughness"
  | "layers" | "crosssection" | "noise" | "interface-width" | "defects"
  | "fourd" | "projectcompare";

export interface ToolWindowState {
  kind: ToolKind;
  x: number;
  y: number;
  z: number;
}

/** The named workspace currently loaded (null = an unsaved "Default"
 *  session). Drives the menu-bar workspace switcher (design WS4b). */
export interface WorkspaceRef {
  slug: string;
  name: string;
}
