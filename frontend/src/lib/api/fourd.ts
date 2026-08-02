// Typed client for the 4D-STEM endpoints (PLAN_4DSTEM #4, routes/fourd.py).
// list/nav/meta are ordinary JSON GETs; pattern/mean-pattern decode the same
// normalized-uint16 wire format as `/image/{id}/data16` (see
// `decodeRaster16` in ./core) since the route reuses `encode_raster_u16`.
// virtual-detector is the one write endpoint — it returns an ImageMeta, the
// same shape `/fourd/{id}/nav` does, so both flow into the normal image
// store via `useViewer().ingestDerived`.

import { decodeRaster16, type FourDMeta, type ImageMeta, type Raster16 } from "./core";
import { json, post } from "./transport";

export async function listFourD(): Promise<FourDMeta[]> {
  return json(await fetch("/api/fourd"));
}

export async function fetchFourDMeta(id: string): Promise<FourDMeta> {
  return json(await fetch(`/api/fourd/${id}/meta`));
}

/** Close a 4D dataset server-side, releasing its file handle (it would
 *  otherwise stay open for the server's lifetime). Nav images and
 *  virtual-detector maps already derived from it are ordinary images in
 *  the separate image store and are NOT affected — see
 *  routes/fourd.py's `close_fourd` docstring. */
export async function closeFourD(id: string): Promise<void> {
  await json(await fetch(`/api/fourd/${id}`, { method: "DELETE" }));
}

/** Registers (idempotently) and returns the nav image's ImageMeta. Callers
 *  decide whether to also `useViewer().ingestDerived([meta])` to surface it
 *  on the main Stage/filmstrip — this alone does not touch the viewer store. */
export async function fetchFourDNav(id: string): Promise<ImageMeta> {
  return json(await fetch(`/api/fourd/${id}/nav`));
}

async function fetchRaster16(
  url: string,
  options?: { signal?: AbortSignal },
): Promise<Raster16> {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`fourd request failed: ${res.status}`);
  return decodeRaster16(res);
}

/** One diffraction pattern at scan position (y, x), uint16-encoded. */
export function fetchFourDPattern(
  id: string,
  y: number,
  x: number,
  options?: { signal?: AbortSignal },
): Promise<Raster16> {
  return fetchRaster16(`/api/fourd/${id}/pattern?y=${y}&x=${x}`, options);
}

/** The scan-averaged diffraction pattern, uint16-encoded. */
export function fetchFourDMeanPattern(
  id: string,
  options?: { signal?: AbortSignal },
): Promise<Raster16> {
  return fetchRaster16(`/api/fourd/${id}/mean-pattern`, options);
}

export type ApertureShape = "circle" | "annulus";

export interface VirtualDetectorRequest {
  center_ky: number | null;
  center_kx: number | null;
  inner_r: number;
  outer_r: number;
  shape: ApertureShape;
  name: string | null;
}

/** Derive a virtual/annular-detector map. `center_*` null lets the server
 *  auto-center from the mean pattern (inner_r is ignored server-side for
 *  shape "circle"). Returns the derived map's ImageMeta, same shape as
 *  `/fourd/{id}/nav` — ingest it the same way. */
export function computeVirtualDetector(
  id: string,
  body: VirtualDetectorRequest,
): Promise<ImageMeta> {
  return post(`/api/fourd/${id}/virtual-detector`, body);
}
