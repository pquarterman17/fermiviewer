// Filter/transform catalogue for the GUI v2 Tools panel (the in-panel
// home that replaced the Image-menu filter list). Framework-agnostic data
// only (handoff §5: lib/ holds no React) so the panel, Batch Apply, and
// tests share one source of truth for tool order, grouping, and params.

import type { ParamField } from "./params";

export type TransformGroup = "Filters" | "Transform Image" | "Segment";

/** How a tool runs: a POST /filter kind, a parameterless geometry op
 *  (via stageOps.applyGeometry), or crop-to-ROI (via stageOps.cropToRoi). */
export type TransformVia = "filter" | "geometry" | "crop";

export interface TransformTool {
  label: string;
  glyph: string;
  group: TransformGroup;
  /** applyFilter kind, geometry op, or "crop". */
  kind: string;
  via: TransformVia;
  fields?: ParamField[];
  /** Included in Image ▸ Batch Apply (preserves the legacy FILTER_DEFS
   *  set: the 9 filters + rotate90/fliph/flipv). */
  batch?: boolean;
}

export const TRANSFORM_GROUPS: TransformGroup[] = [
  "Filters",
  "Transform Image",
  "Segment",
];

const num = (
  key: string,
  label: string,
  dflt: number,
  hint?: string,
): ParamField => ({ key, label, type: "number", default: dflt, hint });

export const TRANSFORM_TOOLS: TransformTool[] = [
  // — Filters —
  {
    label: "Gaussian Blur", glyph: "◍", group: "Filters",
    kind: "gaussian", via: "filter", batch: true,
    fields: [num("sigma", "Sigma (px)", 2)],
  },
  {
    label: "Median Filter", glyph: "▦", group: "Filters",
    kind: "median", via: "filter", batch: true,
    fields: [
      { key: "window_size", label: "Window", type: "select",
        default: "3", options: ["3", "5", "7"] },
    ],
  },
  {
    label: "Unsharp Mask", glyph: "◆", group: "Filters",
    kind: "unsharp", via: "filter", batch: true,
    fields: [num("sigma", "Sigma (px)", 2), num("amount", "Amount", 1)],
  },
  {
    label: "Butterworth", glyph: "≈", group: "Filters",
    kind: "butterworth", via: "filter", batch: true,
    fields: [
      num("low_cutoff", "Low cutoff (0=off)", 0.05),
      num("high_cutoff", "High cutoff (0–1]", 0.5),
      num("order", "Order", 2),
    ],
  },
  {
    label: "CLAHE", glyph: "◑", group: "Filters",
    kind: "clahe", via: "filter", batch: true,
    fields: [num("clip_limit", "Clip limit", 0.01), num("num_bins", "Bins", 256)],
  },
  {
    label: "Bin", glyph: "⊞", group: "Filters",
    kind: "bin", via: "filter", batch: true,
    fields: [num("bin_size", "Bin size", 2)],
  },
  {
    label: "Plane Level", glyph: "▱", group: "Filters",
    kind: "plane_level", via: "filter", batch: true,
  },
  // — Transform Image —
  {
    label: "Rotate 90° CW", glyph: "↻", group: "Transform Image",
    kind: "rotate90", via: "geometry", batch: true,
  },
  {
    label: "Rotate 90° CCW", glyph: "↺", group: "Transform Image",
    kind: "rotate270", via: "geometry",
  },
  {
    label: "Rotate 180°", glyph: "⟳", group: "Transform Image",
    kind: "rotate180", via: "geometry",
  },
  {
    label: "Flip Horizontal", glyph: "⇄", group: "Transform Image",
    kind: "fliph", via: "geometry", batch: true,
  },
  {
    label: "Flip Vertical", glyph: "⇅", group: "Transform Image",
    kind: "flipv", via: "geometry", batch: true,
  },
  {
    label: "Crop to ROI", glyph: "◳", group: "Transform Image",
    kind: "crop", via: "crop",
  },
  // — Segment —
  {
    label: "Morphology", glyph: "⬡", group: "Segment",
    kind: "morph", via: "filter", batch: true,
    fields: [
      { key: "operation", label: "Operation", type: "select",
        default: "open", options: ["erode", "dilate", "open", "close"] },
      num("radius", "Radius (px)", 1),
      { key: "shape", label: "Element", type: "select",
        default: "square", options: ["square", "disk"] },
    ],
  },
  {
    label: "Multi-Otsu", glyph: "◧", group: "Segment",
    kind: "multiotsu", via: "filter", batch: true,
    fields: [
      { key: "n_classes", label: "Classes", type: "select",
        default: "3", options: ["2", "3", "4", "5"] },
    ],
  },
];

/** Subset offered in Image ▸ Batch Apply, in the legacy FILTER_DEFS shape
 *  + order (Gaussian first). Derived from the catalogue's `batch` flag so
 *  the panel and the batch dialog never drift. */
export const BATCH_FILTERS: {
  label: string;
  kind: string;
  fields?: ParamField[];
}[] = TRANSFORM_TOOLS.filter((t) => t.batch).map(({ label, kind, fields }) => ({
  label,
  kind,
  fields,
}));
