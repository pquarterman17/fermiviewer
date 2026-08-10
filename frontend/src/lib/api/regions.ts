// Typed client for POST /api/regions/propose (PROJECT_WORKFLOW_PLAN.md item
// 16 — routes/regions.py): edge auto-detect assist. Mirrors its Pydantic
// wire models — keep in sync.
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
