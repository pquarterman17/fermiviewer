// Capture-mode step copy for the on-stage capture banner (GUI v2).
// One entry per banner-worthy CaptureMode; "none" and "fixed-zoom" are
// intentionally omitted (no banner — fixed-zoom has its own badge).
// For click modes, steps.length must equal the click count in Stage's
// CLICKS map so the STEP n/N readout lines up with the captured points.

import type { CaptureMode } from "../store/viewer";

export interface CaptureStep {
  label: string;
  steps: string[];
}

export const CAPTURE_STEPS: Partial<Record<CaptureMode, CaptureStep>> = {
  distance: { label: "Distance", steps: ["Click point A", "Click point B"] },
  profile: { label: "Line profile", steps: ["Click start", "Click end"] },
  angle: {
    label: "Angle",
    steps: ["Click vertex", "Click ray 1", "Click ray 2"],
  },
  polyline: {
    label: "Polyline",
    steps: ["Click vertices — double-click to finish"],
  },
  text: { label: "Text", steps: ["Click to place text"] },
  arrow: { label: "Arrow", steps: ["Click tail", "Click head"] },
  box: { label: "Box", steps: ["Click corner", "Click opposite corner"] },
  circle: { label: "Circle", steps: ["Click center", "Click edge"] },
  roi: { label: "ROI", steps: ["Drag a box"] },
  ellipse: { label: "Ellipse", steps: ["Drag a box"] },
  "box-profile": { label: "Box profile", steps: ["Drag a box along the feature"] },
  "crop-save": { label: "Save Cropped Region", steps: ["Drag a box to crop and save as a new image"] },
  zoom: { label: "Box zoom", steps: ["Drag a box to zoom"] },
};
