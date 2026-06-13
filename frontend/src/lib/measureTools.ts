// Measure-tool catalogue for the GUI v2 command list (MeasurePanel).
// Framework-agnostic data only (handoff §5: lib/ holds no React) so the
// panel and tests share one source of truth for tool order + grouping.

import type { CaptureMode } from "../store/viewer";

export type MeasureGroup =
  | "Profiles & Distance"
  | "Regions of Interest"
  | "Annotations";

export interface MeasureTool {
  label: string;
  glyph: string;
  kind: CaptureMode;
  group: MeasureGroup;
}

export const MEASURE_GROUPS: MeasureGroup[] = [
  "Profiles & Distance",
  "Regions of Interest",
  "Annotations",
];

export const MEASURE_TOOLS: MeasureTool[] = [
  { label: "Profile", glyph: "∿", kind: "profile", group: "Profiles & Distance" },
  { label: "Box Prof", glyph: "⧈", kind: "box-profile", group: "Profiles & Distance" },
  { label: "Distance", glyph: "↔", kind: "distance", group: "Profiles & Distance" },
  { label: "Angle", glyph: "∠", kind: "angle", group: "Profiles & Distance" },
  { label: "Polyline", glyph: "⌇", kind: "polyline", group: "Profiles & Distance" },
  { label: "ROI", glyph: "▭", kind: "roi", group: "Regions of Interest" },
  { label: "Ellipse", glyph: "◯", kind: "ellipse", group: "Regions of Interest" },
  { label: "Text", glyph: "T", kind: "text", group: "Annotations" },
  { label: "Arrow", glyph: "➹", kind: "arrow", group: "Annotations" },
  { label: "Box", glyph: "□", kind: "box", group: "Annotations" },
  { label: "Circle", glyph: "◌", kind: "circle", group: "Annotations" },
];
