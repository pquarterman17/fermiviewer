// Diffraction workshop geometry & ring-matching helpers, extracted verbatim
// from DiffractionWorkshop.tsx (repo-health #33): ROI drawing-state types,
// the matched-phase ring SVG builders (port of drawMatchedRings.m), and the
// d-spacing → radius conversion used for the typed-d preview ring.

import type { AnalysisRoi, PhaseCandidate } from "../../../lib/api";

// ── ROI drawing state ────────────────────────────────────────────────
export type RoiMode = "none" | "rect" | "circle";

export interface RoiDraw {
  mode: RoiMode;
  p1: { x: number; y: number } | null; // first click (display px)
  p2: { x: number; y: number } | null; // second click / live drag
}

/** Convert display-px point to 0-based full-image coords. */
function toImg(pt: { x: number; y: number }, scale: number) {
  return { r: Math.round(pt.y / scale), c: Math.round(pt.x / scale) };
}

/** Build an AnalysisRoi from two display-px points given a display scale. */
export function roiFromPoints(
  draw: RoiDraw,
  scale: number,
): AnalysisRoi | null {
  if (!draw.p1 || !draw.p2) return null;
  const a = toImg(draw.p1, scale);
  const b = toImg(draw.p2, scale);
  if (draw.mode === "rect") {
    return {
      kind: "rect",
      r0: Math.min(a.r, b.r),
      c0: Math.min(a.c, b.c),
      r1: Math.max(a.r, b.r),
      c1: Math.max(a.c, b.c),
    };
  }
  if (draw.mode === "circle") {
    const radius = Math.round(Math.hypot(b.r - a.r, b.c - a.c));
    return { kind: "circle", cr: a.r, cc: a.c, radius };
  }
  return null;
}

// ── matched-ring helpers ─────────────────────────────────────────────

/** Build SVG ring overlays for a matched-phase candidate.
 *
 *  Port of drawMatchedRings.m:
 *    for k = 1:numel(candidate.matchedD)
 *        R = measuredR(k);
 *        plot ring at radius R centred on the pattern centre
 *        label with (hkl) at 1.05 R
 *
 *  In MATLAB, measuredR is the full array of spot radii AND matchedD is
 *  the subset for matched spots; MATLAB uses matchedD length to index
 *  measuredR sequentially.  The Python port stores matched_d as the
 *  d-spacings for matched spots.  We reconstruct which original spot
 *  corresponds to each matched_d by finding the spot whose measured radius
 *  yields the closest d-spacing via the FFT formula (d = W*px/R), greedily
 *  consuming spot indices in order — matching the MATLAB is=1:nSpots loop.
 *
 *  imgW: full image width (pixels), used for FFT-mode d↔R conversion.
 *  pixelSizeMm: pixel calibration (forwarded from the index call).
 */
/** Map each matched spot k → its index into the posted spots[]. Prefers the
 *  exact `matched_idx` from the index response; falls back to the old greedy
 *  radius reconstruction for responses that predate that field. */
export function matchedSpotIndices(
  candidate: PhaseCandidate,
  measuredR: number[],
  imgW: number,
  pixelSizeMm: number,
): number[] {
  const { matched_d, matched_idx } = candidate;
  if (Array.isArray(matched_idx) && matched_idx.length === matched_d.length) {
    return matched_idx;
  }
  // legacy fallback: d_meas[i] = W*px/R[i], greedily match each matched_d
  const dPerSpot = measuredR.map((R) =>
    R > 0 ? (imgW * pixelSizeMm) / R : Infinity,
  );
  const used = new Set<number>();
  return matched_d.map((dm) => {
    let best = -1;
    let bestFrac = Infinity;
    for (let i = 0; i < dPerSpot.length; i++) {
      if (used.has(i)) continue;
      const frac = Math.abs(dPerSpot[i] - dm) / dm;
      if (frac < bestFrac) {
        bestFrac = frac;
        best = i;
      }
    }
    if (best >= 0) used.add(best);
    return best;
  });
}

export function matchedRingSvg(
  candidate: PhaseCandidate,
  measuredR: number[],
  center: [number, number],   // 1-based (row, col)
  scale: number,
  imgW: number,
  pixelSizeMm: number,
  spots: [number, number][],
  showRings: boolean,
  showLabels: boolean,
): React.ReactNode[] {
  const cx = (center[1] - 0.5) * scale;  // 1-based col → display px
  const cy = (center[0] - 0.5) * scale;
  const nodes: React.ReactNode[] = [];
  const { matched_hkl, matched_d } = candidate;
  if (!matched_d || matched_d.length === 0 || measuredR.length === 0) return [];

  const idx = matchedSpotIndices(candidate, measuredR, imgW, pixelSizeMm);

  for (let k = 0; k < matched_d.length; k++) {
    const i = idx[k];
    if (i < 0 || i >= measuredR.length) continue;
    const R = measuredR[i] * scale;
    const hkl = matched_hkl[k] ?? [0, 0, 0];

    if (showRings) {
      nodes.push(
        <circle key={`mring-${k}`} cx={cx} cy={cy} r={R} fill="none"
          stroke="#22c55e" strokeWidth={1} />,
      );
      // on-ring hkl tag only when per-spot labels aren't carrying it
      if (!showLabels) {
        nodes.push(
          <text key={`mrt-${k}`} x={cx + R * 1.05} y={cy} fill="#22c55e"
            fontSize={9} dominantBaseline="middle">
            ({hkl.join("")})
          </text>,
        );
      }
    }

    // #4: hkl + measured-d label pinned at the matched spot's own position
    if (showLabels && spots[i]) {
      const [row, col] = spots[i];
      const sx = (col - 0.5) * scale;
      const sy = (row - 0.5) * scale;
      nodes.push(
        <g key={`mlbl-${k}`}>
          <circle cx={sx} cy={sy} r={3} fill="#22c55e" />
          <text x={sx + 6} y={sy - 4} fill="#22c55e" fontSize={9}
            dominantBaseline="middle" stroke="#000" strokeWidth={0.5}
            paintOrder="stroke">
            ({hkl.join("")}) {matched_d[k].toFixed(3)}Å
          </text>
        </g>,
      );
    }
  }
  return nodes;
}

// ── d-spacing → radius (FFT mode, frontend mirror of d_spacing_to_radius) ──

/** Convert a d-spacing (Å) to a ring radius in display pixels.
 *
 *  FFT mode formula (drawRingOverlay.m / d_spacing_to_radius in calc):
 *    R_px = W * pixelSize / d
 *  where W = image width in px, pixelSize in Å/px.
 *
 *  Camera-mode formula (when cameraLengthMm is provided):
 *    sin θ = λ / (2 d);  R_px = L_mm * tan(2θ) / pixelSize_mm_per_px
 *  λ (Å) = 12.264 / sqrt(kV * (1 + 0.9788e-3 * kV)) [non-relativistic approx
 *  used here only for display preview; the backend uses the exact CODATA formula].
 */
export function dSpacingToRadiusPx(
  dAng: number,
  imgW: number,
  pixelSizeMm: number,
  cameraLengthMm: number | null,
  accKv: number,
  displayScale: number,
): number | null {
  if (dAng <= 0) return null;
  if (!cameraLengthMm) {
    // FFT mode: pixel_size treated as Å/px (the workshop stores mm, but for
    // FFT-mode the user typically enters the real-space calibration in nm or
    // similar; the backend always uses consistent units — here we mirror the
    // FFT formula for the preview ring without unit-conversion since the scale
    // only matters relatively): R_img = W * pixelSize / d
    const rImg = (imgW * pixelSizeMm) / dAng;
    return rImg * displayScale;
  }
  // TEM camera mode
  const kv = accKv;
  const lam = 12.264 / Math.sqrt(kv * (1 + 0.9788e-3 * kv)); // Å approx
  const sinTheta = lam / (2 * dAng);
  if (sinTheta > 1) return null;
  const rMm = cameraLengthMm * Math.tan(2 * Math.asin(sinTheta));
  const rImg = rMm / pixelSizeMm;
  return rImg * displayScale;
}
