// Typed client for the 4D-STEM endpoints (PLAN_4DSTEM #4, routes/fourd.py).
// list/nav/meta are ordinary JSON GETs; pattern/mean-pattern decode the same
// normalized-uint16 wire format as `/image/{id}/data16` (see
// `decodeRaster16` in ./core) since the route reuses `encode_raster_u16`.
// virtual-detector is the one write endpoint — it returns an ImageMeta, the
// same shape `/fourd/{id}/nav` does, so both flow into the normal image
// store via `useViewer().ingestDerived`.

import { record } from "../macro";
import { decodeRaster16, type FourDMeta, type ImageMeta, type Raster16 } from "./core";
import { formatApiDetail, json } from "./transport";

/** Thrown for a 404 from any per-id 4D endpoint — the dataset is unknown
 *  server-side (closed elsewhere, or a stale selection surviving past this
 *  store's last successful list fetch). A distinct type (rather than a
 *  generic Error whose message happens to contain "unknown 4D dataset id")
 *  is what lets store/fourd.ts degrade a stale selection to "cleared +
 *  refreshed list" instead of leaving a per-dataset error note that just
 *  keeps re-failing on every subsequent action (PLAN_4DSTEM #14). */
export class FourDNotFoundError extends Error {}

/** Like transport.ts's `json`, but a 404 raises `FourDNotFoundError`
 *  instead of a plain `Error` so 4D-specific callers can tell "this
 *  dataset id is gone" apart from any other failure. */
async function fourdJson<T>(res: Response): Promise<T> {
  if (res.status === 404) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = formatApiDetail(body.detail, detail);
    } catch {
      /* non-JSON error body */
    }
    throw new FourDNotFoundError(detail);
  }
  return json<T>(res);
}

export async function listFourD(): Promise<FourDMeta[]> {
  return fourdJson(await fetch("/api/fourd"));
}

export async function fetchFourDMeta(id: string): Promise<FourDMeta> {
  return fourdJson(await fetch(`/api/fourd/${id}/meta`));
}

/** Close a 4D dataset server-side, releasing its file handle (it would
 *  otherwise stay open for the server's lifetime). Nav images and
 *  virtual-detector maps already derived from it are ordinary images in
 *  the separate image store and are NOT affected — see
 *  routes/fourd.py's `close_fourd` docstring. */
export async function closeFourD(id: string): Promise<void> {
  await fourdJson(await fetch(`/api/fourd/${id}`, { method: "DELETE" }));
}

/** Registers (idempotently) and returns the nav image's ImageMeta. Callers
 *  decide whether to also `useViewer().ingestDerived([meta])` to surface it
 *  on the main Stage/filmstrip — this alone does not touch the viewer store. */
export async function fetchFourDNav(id: string): Promise<ImageMeta> {
  return fourdJson(await fetch(`/api/fourd/${id}/nav`));
}

async function fetchRaster16(
  url: string,
  options?: { signal?: AbortSignal },
): Promise<Raster16> {
  const res = await fetch(url, options);
  if (res.status === 404) {
    let detail = res.statusText;
    try {
      const body = (await res.json()) as { detail?: unknown };
      detail = formatApiDetail(body.detail, detail);
    } catch {
      /* binary/non-JSON error body */
    }
    throw new FourDNotFoundError(detail);
  }
  if (!res.ok) throw new Error(`fourd request failed: ${res.status}`);
  return decodeRaster16(res);
}

/** Like transport.ts's `post`, but routes the response through `fourdJson`
 *  so a 404 (a stale/closed dataset id) raises `FourDNotFoundError` here
 *  too — `reshapeFourD`/`computeVirtualDetector` both target an existing
 *  4D id and can 404 exactly like the GET endpoints above. */
async function fourdPost<T>(url: string, body: unknown): Promise<T> {
  record(url, body as Record<string, unknown>);
  return fourdJson<T>(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
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

/** Re-raster a headerless acquisition (Merlin `.mib`) to `rows × cols`.
 *  The server RE-OPENS the file under the new shape, keeping the same 4D id,
 *  and returns the updated meta. 422 when rows × cols is not the frame count
 *  or the format states its own raster. */
export function reshapeFourD(
  id: string,
  rows: number,
  cols: number,
): Promise<FourDMeta> {
  return fourdPost(`/api/fourd/${id}/reshape`, { rows, cols });
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
  return fourdPost(`/api/fourd/${id}/virtual-detector`, body);
}
