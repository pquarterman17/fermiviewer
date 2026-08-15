// Typed client for POST /api/regions/propose (PROJECT_WORKFLOW_PLAN.md item
// 16 — routes/regions.py) and POST /api/analyze/fit-shape
// (SHAPE_ANALYSIS_PLAN.md Wave-2 #5 — routes/shape_id.py). Mirrors their
// Pydantic wire models — keep in sync.
//
// Segmentation PROPOSES an outline from a seed click or rough rect; the
// frontend (RegionsCard.tsx) lands the returned points as an ordinary
// editable `polygon` measure via the store's addMeasure action — there is
// no separate "detected region" concept anywhere in this stack.

import { post } from "./transport";

export interface ProposeRegionRequest {
  image_id: string;
  /** normalized (x, y) in [0, 1] — a click point selecting WHICH region
   *  to propose. */
  seed?: [number, number];
  /** normalized (x0, y0, x1, y1) in [0, 1] — a rough box seed; when given
   *  without `seed`, its centre is used as the seed point, and either way
   *  it also localizes the segmentation search server-side (regions.py). */
  rect?: [number, number, number, number];
  n_classes?: number;
  morph_radius?: number;
  tolerance?: number;
}

export interface ProposeRegionResponse {
  /** normalized (x, y) pairs, NOT closed — the same convention as
   *  store/viewerTypes.ts Measure.pts (as [x, y] tuples on the wire). */
  points: [number, number][];
  area_px: number;
  area_calibrated: number | null;
  unit: string;
}

/** Ask the server to propose a region outline from a seed. 404 for an
 *  unknown image, 422 for an unusable seed (out of bounds, a rect too
 *  small to segment, or one that lands on no detectable region) — never
 *  a 500; `post` rejects with an Error carrying the server's detail. */
export function proposeRegion(
  req: ProposeRegionRequest,
): Promise<ProposeRegionResponse> {
  return post("/api/regions/propose", req);
}

// ── /api/analyze/fit-shape (SHAPE_ANALYSIS_PLAN.md Wave-2 #5) ─────────

export interface FitShapeRequest {
  /** `[[row, col], ...]`, px, 1-based (routes/shape_id.py's
   *  `FitShapeRequest.points`). NOT required to be explicitly closed —
   *  the last point need not repeat the first; verified against
   *  tests/test_api_shape_id.py, which fits both circle and ellipse from
   *  open point lists (e.g. `_circle_points` uses `linspace(...,
   *  endpoint=False)`). The row/col-vs-x/y and 0-vs-1-based conversion
   *  from a store `Measure`'s normalized `{x, y}` vertices happens at the
   *  call site (RegionsCard.tsx `measurePtsToFitPoints`) — see that
   *  function's comment for the verified basing evidence. */
  points: [number, number][];
}

export interface CircleFitResult {
  cy: number;
  cx: number;
  r: number;
  rms: number;
}

export interface EllipseFitResult {
  cy: number;
  cx: number;
  a: number;
  b: number;
  /** radians, measured from the image +col/x axis toward +row/y — same
   *  convention as calc/diffraction_calib.py's `EllipseFit.theta`
   *  (calc/shape_fit.py reuses that fit directly). Degrees for display
   *  are derived at the call site, never sent back on the wire. */
  theta_rad: number;
  rms: number;
}

export interface FitShapeResponse {
  circle: CircleFitResult;
  ellipse: EllipseFitResult;
}

/** Fit a circle and an ellipse to a closed polygon's vertices
 *  (routes/shape_id.py POST /analyze/fit-shape). 422 when there are too
 *  few points for one shape or the other (circle needs >= 3 distinct
 *  points, ellipse >= 5) — `post` rejects with an Error carrying the
 *  server's detail either way, never a 500. */
export function fitShape(req: FitShapeRequest): Promise<FitShapeResponse> {
  return post("/api/analyze/fit-shape", req);
}
