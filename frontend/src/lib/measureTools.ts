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
  { label: "Polygon", glyph: "⬠", kind: "polygon", group: "Regions of Interest" },
  { label: "Lasso", glyph: "➰", kind: "lasso", group: "Regions of Interest" },
  { label: "Text", glyph: "T", kind: "text", group: "Annotations" },
  { label: "Arrow", glyph: "➹", kind: "arrow", group: "Annotations" },
  { label: "Box", glyph: "□", kind: "box", group: "Annotations" },
  { label: "Circle", glyph: "◌", kind: "circle", group: "Annotations" },
];

/** How each tool is placed on the image — the arming tooltip used to say
 *  "drag on the image" for every tool, which was untrue for the click-
 *  driven ones (angle, polyline, polygon, text). */
const PLACE_HINT: Partial<Record<CaptureMode, string>> = {
  profile: "drag along the line, or click start then end",
  distance: "drag between the points, or click one then the other",
  arrow: "drag from tail to head, or click tail then head",
  box: "drag corner to corner, or click two opposite corners",
  circle: "drag from centre to edge, or click centre then edge",
  angle: "click the vertex, then a point on each ray",
  polyline: "click each vertex, double-click to finish",
  polygon: "click each vertex, click the first again or double-click to close",
  text: "click where the text goes",
};

/** Tooltip for arming a measure tool. */
export function measureToolTitle(t: MeasureTool): string {
  const how = PLACE_HINT[t.kind] ?? "drag on the image to place it";
  return `Arm the ${t.label} tool — ${how} (click again to disarm)`;
}
