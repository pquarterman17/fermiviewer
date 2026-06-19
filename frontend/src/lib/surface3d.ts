// Pure projection + orbit math for the 3D surface plot.
// All functions are stateless; they can be tested in vitest without a DOM.
//
// Coordinate convention (matching MATLAB view(az, el)):
//   az  — azimuth in degrees, 0 = "east" (+X), positive = counter-clockwise
//         when viewed from above (same sign as MATLAB's azimuth argument).
//   el  — elevation in degrees above the XY plane (0 = horizontal, 90 = top-down).
//
// The mesh lives in a unit cube [0,1]³ (gx/gw, gy/gh, z/zRange).
// Project uses a simple parallel (orthographic) projection rotated by az/el,
// the same visual class as MATLAB's default surf() view.

export interface ProjectedPt {
  sx: number; // screen x
  sy: number; // screen y
}

const DEG = Math.PI / 180;

/** Rotate a unit-cube 3-D point [u,v,w] by azimuth + elevation and return
 *  2-D screen coordinates scaled into [canvasW × canvasH] with `margin` px
 *  of padding on each side.  Returns {sx, sy}. */
export function project(
  u: number,
  v: number,
  w: number,
  az: number,
  el: number,
  canvasW: number,
  canvasH: number,
  margin: number,
): ProjectedPt {
  // Rotate around Z-axis by azimuth (−az so positive az = CCW from above)
  const a = -az * DEG;
  const e = el * DEG;

  const cosA = Math.cos(a);
  const sinA = Math.sin(a);
  const cosE = Math.cos(e);
  const sinE = Math.sin(e);

  // Centre the unit cube at origin first
  const uc = u - 0.5;
  const vc = v - 0.5;
  const wc = w - 0.5;

  // Azimuth rotation (around world Z)
  const x1 = uc * cosA - vc * sinA;
  const y1 = uc * sinA + vc * cosA;
  const z1 = wc;

  // Elevation rotation (around rotated X axis — tilt up/down).
  // Positive el lifts z above the horizon; z1 contributes positively to yf
  // so that the top of the mesh (z1 > 0) projects above canvas centre.
  const xf = x1;
  const yf = y1 * cosE + z1 * sinE;
  const zf = -y1 * sinE + z1 * cosE; // unused for parallel projection

  void zf; // intentional — parallel projection ignores depth

  // Map to canvas: scale to fill with margin.
  // After the rotations the projected extents are at most ~√2 in each axis,
  // so we normalise by 0.75 * √2 ≈ 1.06 and add 0.5 to re-centre.
  const scale = Math.min(canvasW, canvasH) * 0.5 - margin;
  const norm = 0.75 * Math.sqrt(2);

  return {
    sx: canvasW / 2 + (xf / norm) * scale,
    sy: canvasH / 2 - (yf / norm) * scale,
  };
}

/** Normalise az into (−180, 180] so the drag accumulator doesn't overflow. */
export function normaliseAz(az: number): number {
  let a = az % 360;
  if (a > 180) a -= 360;
  if (a <= -180) a += 360;
  return a;
}

/** Clamp elevation to [−89, 89] so we never hit degenerate top/bottom views. */
export function clampEl(el: number): number {
  return Math.max(-89, Math.min(89, el));
}

/** Convert an (az, el) drag delta in pointer pixels to az/el deltas.
 *  dx → azimuth, dy → elevation; sensitivity calibrated to feel natural. */
export function dragToOrbit(
  dx: number,
  dy: number,
  sensitivity = 0.4,
): { dAz: number; dEl: number } {
  return { dAz: dx * sensitivity, dEl: -dy * sensitivity };
}

/** MATLAB default initial view angles for surf(). */
export const DEFAULT_AZ = 45;
export const DEFAULT_EL = 30;
