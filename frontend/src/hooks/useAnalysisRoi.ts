import { useEffect, useMemo, useState } from "react";

import { useViewer, type Measure, type SavedRoi } from "../store/viewer";

export type AnalysisRoi = [number, number, number, number];

interface RoiOption {
  value: string;
  label: string;
}

const NO_MEASURES: Measure[] = [];
const NO_SAVED: SavedRoi[] = [];

/** Convert normalized viewer coordinates to a 1-based inclusive API box. */
export function toAnalysisRoi(
  item: Pick<Measure, "kind" | "pts">,
  shape: number[],
): AnalysisRoi | null {
  if ((item.kind !== "roi" && item.kind !== "ellipse") || item.pts.length < 2) {
    return null;
  }
  const [h, w] = shape;
  if (!Number.isFinite(h) || !Number.isFinite(w) || h < 1 || w < 1) return null;
  const xs = item.pts.map((p) => Math.min(1, Math.max(0, p.x)) * w);
  const ys = item.pts.map((p) => Math.min(1, Math.max(0, p.y)) * h);
  const c1 = Math.min(w, Math.floor(Math.min(...xs)) + 1);
  const c2 = Math.max(c1, Math.min(w, Math.ceil(Math.max(...xs))));
  const r1 = Math.min(h, Math.floor(Math.min(...ys)) + 1);
  const r2 = Math.max(r1, Math.min(h, Math.ceil(Math.max(...ys))));
  return [r1, c1, r2, c2];
}

/** ROI-local layer depths/traces translated to full-image stage coordinates. */
export function layerOverlayCoordinates(
  axis: "y" | "x",
  positions: number[],
  traces: (number[] | null)[],
  roi: AnalysisRoi | null,
): {
  interfaces: number[];
  traces: (number[] | null)[];
  lateralOffset: number;
  lateralRange?: [number, number];
  depthRange?: [number, number];
} {
  if (!roi) return { interfaces: positions, traces, lateralOffset: 0 };
  const depthOffset = (axis === "y" ? roi[0] : roi[1]) - 1;
  const lateralOffset = (axis === "y" ? roi[1] : roi[0]) - 1;
  return {
    interfaces: positions.map((p) => p + depthOffset),
    traces: traces.map((trace) => trace?.map((p) => p + depthOffset) ?? null),
    lateralOffset,
    lateralRange: axis === "y" ? [roi[1] - 1, roi[3]] : [roi[0] - 1, roi[2]],
    depthRange: axis === "y" ? [roi[0] - 1, roi[2]] : [roi[1] - 1, roi[3]],
  };
}

export function roiLocalDepths(
  axis: "y" | "x",
  positions: number[],
  roi: AnalysisRoi | null,
): number[] {
  if (!roi) return positions;
  const offset = (axis === "y" ? roi[0] : roi[1]) - 1;
  return positions.map((p) => p - offset);
}

/** Supplies Whole image, the selected drawn ROI, and named saved ROIs. */
export function useAnalysisRoi(imageId: string | null, shape: number[]) {
  const measures = useViewer((s) =>
    imageId ? (s.measures[imageId] ?? NO_MEASURES) : NO_MEASURES,
  );
  const saved = useViewer((s) =>
    imageId ? (s.savedRois[imageId] ?? NO_SAVED) : NO_SAVED,
  );
  const selectedId = useViewer((s) => s.selectedMeasure);
  const [choice, setChoice] = useState("whole");

  useEffect(() => setChoice("whole"), [imageId]);

  const selected = measures.find(
    (m) => m.id === selectedId && (m.kind === "roi" || m.kind === "ellipse"),
  );
  const options = useMemo<RoiOption[]>(() => {
    const result: RoiOption[] = [{ value: "whole", label: "Whole image" }];
    if (selected) result.push({ value: "selected", label: "Selected ROI" });
    result.push(...saved.map((r) => ({ value: `saved:${r.id}`, label: r.name })));
    return result;
  }, [selected, saved]);
  const validChoice = options.some((o) => o.value === choice) ? choice : "whole";
  const item = validChoice === "selected"
    ? selected
    : saved.find((r) => validChoice === `saved:${r.id}`);
  const roi = useMemo(
    () => item ? toAnalysisRoi(item, shape) : null,
    [item, shape],
  );
  const label = options.find((o) => o.value === validChoice)?.label ?? "Whole image";
  return { choice: validChoice, setChoice, options, roi, label };
}
