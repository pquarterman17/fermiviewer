// Turning a layers result into the stage overlay, and counting how far the
// operator has moved from the detector.
//
// Split out of `LayersWorkshop.tsx` when the detected-vs-edited display
// pushed that module past the 500-line guard. The seam was already there:
// everything here is coordinate work — profile depths to image rows — and
// nothing here owns analysis parameters or React state.

import { layerOverlayCoordinates, type AnalysisRoi } from "../../../hooks/useAnalysisRoi";
import type { LayersResult } from "../../../lib/api";
import type { LayersOverlayState } from "../../../store/viewerTypes";

/** Two interfaces closer than this are the same one, unmoved. Half a
 *  profile pixel: an erf refit shifts a kept interface by far less, and a
 *  deliberate nudge by far more. */
export const MOVED_TOLERANCE_PX = 0.5;

export function layersOverlayState(
  r: LayersResult,
  imageId: string,
  roi: AnalysisRoi | null,
  /** the detector's own positions in ROI-local profile depths, or null on a
      freshly detected run where the two coincide */
  detectedLocal: number[] | null,
): LayersOverlayState {
  const tilt =
    r.applied_tilt_deg == null
      ? null
      : { tiltDeg: r.applied_tilt_deg, nDepth: r.depth_pos.length };
  const overlay = layerOverlayCoordinates(
    r.axis,
    r.interfaces.map((i) => i.position),
    r.interfaces.map((i) => i.trace),
    roi,
    tilt,
  );
  // Both sets go through the SAME transform. A detected line mapped
  // differently from the edited one would show a gap that is a coordinate
  // bug rather than a disagreement.
  const detected = detectedLocal
    ? layerOverlayCoordinates(
        r.axis,
        detectedLocal,
        detectedLocal.map(() => null),
        roi,
        tilt,
      ).interfaces
    : undefined;
  return {
    imageId,
    axis: r.axis,
    tiltDeg: r.applied_tilt_deg ?? 0,
    ...overlay,
    ...(detected ? { detected } : {}),
  };
}

/** How many interfaces the operator has moved off the detector's guess. */
export function movedFromDetected(
  r: LayersResult | null,
  detectedLocal: number[] | null,
): number {
  if (!r || !detectedLocal) return 0;
  return r.interfaces.filter(
    (i) =>
      !detectedLocal.some(
        (d) => Math.abs(d - i.position) < MOVED_TOLERANCE_PX,
      ),
  ).length;
}
