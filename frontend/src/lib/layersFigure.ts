// The cross-section as a figure: the micrograph with its interfaces, the
// analysed region and the layer labels burned in.
//
// Built out of the export route's measurement annotations rather than a
// new drawing path on the server. Interfaces become `line` measures: a
// plain segment captioned with the text GIVEN, so the labels say layer
// thicknesses instead of the lateral span of the line (what
// `distance`/`profile` compute) and carry no arrowhead implying a
// direction (what `arrow` draws).
//
// The interfaces arrive in the same image-pixel depths the stage overlay
// draws, so what the figure shows is what the operator saw and adjusted,
// not a re-derivation that could disagree with it.

import type { LayersResult } from "./api";
import type { LayersOverlayState } from "../store/viewerTypes";

export interface FigureMeasure {
  kind: string;
  pts: { x: number; y: number }[];
  text?: string;
}

/** Normalised (0-1) endpoints of one interface line, tilt included. */
function interfaceLine(
  overlay: LayersOverlayState,
  depth: number,
  shape: { h: number; w: number },
): { x: number; y: number }[] {
  const horizontal = overlay.axis === "y";
  const lo = overlay.lateralRange?.[0] ?? 0;
  const hi = overlay.lateralRange?.[1] ?? (horizontal ? shape.w : shape.h);
  const tan = Math.tan(((overlay.tiltDeg ?? 0) * Math.PI) / 180);
  // the same pivot-about-the-midpoint the overlay uses, so a tilted stack
  // exports where it was drawn
  const at = (lateral: number) => depth - (lateral - (lo + hi) / 2) * tan;
  const pt = (lateral: number) =>
    horizontal
      ? { x: lateral / shape.w, y: at(lateral) / shape.h }
      : { x: at(lateral) / shape.w, y: lateral / shape.h };
  return [pt(lo), pt(hi)];
}

/**
 * Measures for `POST /api/export` with `include: ["measurements"]`.
 *
 * Every interface gets a line. A layer's thickness labels the interface at
 * its TOP, which is the same pairing the results table uses, so a reader
 * moving between the two is never asked to re-derive which band a number
 * belongs to. The last interface carries no label — there is no layer
 * below it to measure.
 */
export function layersFigureMeasures(
  overlay: LayersOverlayState,
  result: LayersResult,
  shape: { h: number; w: number },
  roi: [number, number, number, number] | null,
): FigureMeasure[] {
  const out: FigureMeasure[] = [];
  if (roi) {
    // 1-based inclusive rect -> normalised corners
    const [r1, c1, r2, c2] = roi;
    out.push({
      kind: "box",
      pts: [
        { x: (c1 - 1) / shape.w, y: (r1 - 1) / shape.h },
        { x: c2 / shape.w, y: r2 / shape.h },
      ],
      text: "analysed region",
    });
  }
  overlay.interfaces.forEach((depth, k) => {
    const band = result.layers.find((l) => l.index === k);
    out.push({
      kind: "line",
      pts: interfaceLine(overlay, depth, shape),
      text: band
        ? `${Number(band.thickness.toPrecision(3))} ${result.unit}`
        : "",
    });
  });
  return out;
}
