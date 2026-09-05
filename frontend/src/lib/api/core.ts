// Typed client for the FastAPI backend (handoff §8). Mirrors the
// Pydantic wire models in src/fermiviewer/models.py — keep in sync.

import type { CapturedResultRef } from "./project";
import { json } from "./transport";

export type DataKind = "image" | "rgb_image" | "spectrum" | "spectrum_image";

export interface ImageMeta {
  id: string;
  name: string;
  kind: DataKind;
  shape: number[];
  dtype: string;
  pixel_size: number | null;
  /** Physical extent per pixel as [row, column], in pixel_unit. Null when
   * either spatial axis is uncalibrated or their units do not agree. */
  pixel_spacing?: [number, number] | null;
  pixel_unit: string;
  value_unit: string;
  n_channels: number | null;
  energy_first: number | null;
  energy_last: number | null;
  energy_units: string;
  stage_tilt_deg: number | null;
  /** Rows of real image above a vendor-baked databar (Thermo Fisher
   *  SEM/FIB TIFFs bake magnification/HV/their own scale bar into the
   *  bottom of the pixels), else null. Server-normalized from the vendor
   *  tag pair — see io.metadata.databar_content_rows — so the scale bar's
   *  default position and Strip Vendor Databar share one number.
   *
   *  Optional rather than `number | null`: the server always sends it, but
   *  absent and null mean the same thing to every consumer ("no bar to
   *  avoid or crop"), so `?? shape[0]` covers both. Nothing in the app
   *  constructs an ImageMeta — they all come off the wire — so this cannot
   *  hide a production site that forgot to set it. */
  content_rows?: number | null;
  meta: Record<string, string | number | boolean>;
}

export interface Histogram {
  bins: number[];
  counts: number[];
}

/** Wire form of `fermiviewer.datastruct.AxisCal` (models.py's AxisCalOut).
 *  value = (index − origin) × scale; calibrated iff scale is finite/nonzero
 *  AND units is non-empty (mirrors AxisCal.calibrated). */
export interface AxisCalOut {
  scale: number;
  origin: number;
  units: string;
}

export function isAxisCalibrated(a: AxisCalOut): boolean {
  return Number.isFinite(a.scale) && a.scale !== 0 && a.units !== "";
}

/** A 4D-STEM dataset (PLAN_4DSTEM) — deliberately NOT an ImageMeta shape
 *  (no `kind`/`shape` raster fields): it isn't a normal image and has no
 *  render pipeline yet. `is_fourd` discriminates it in a mixed open-result
 *  array; see `isFourDMeta` and store/viewerSession.ts's `ingestImages`. */
export interface FourDMeta {
  id: string;
  name: string;
  is_fourd: true;
  source: string | null;
  scan_shape: number[];
  det_shape: number[];
  dtype: string;
  scan_axes: AxisCalOut[];
  det_axes: AxisCalOut[];
  nav_available: boolean;
  /** Probe positions in the file — what any re-raster has to preserve. */
  n_frames: number;
  /** False when the format records no raster (Merlin `.mib`): the current
   *  `scan_shape` is then the parser's fallback, not the acquisition, and
   *  `reshapeFourD` is how the user corrects it. */
  scan_shape_from_file: boolean;
  /** Plausible `[rows, cols]` re-rasterings, squarest first. Empty when the
   *  shape came from the file. */
  scan_shape_options: number[][];
}

export function isFourDMeta(m: ImageMeta | FourDMeta): m is FourDMeta {
  return (m as FourDMeta).is_fourd === true;
}

export async function openSession(
  paths: string[],
): Promise<(ImageMeta | FourDMeta)[]> {
  return json(
    await fetch("/api/session/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths }),
    }),
  );
}

export async function listImages(): Promise<ImageMeta[]> {
  return json(await fetch("/api/session/images"));
}

/** Dev-only: server-resolved sample file paths (jpeg/dm3/dm4/tif) from
 *  the sibling fermi-viewer corpus. Empty when the corpus is absent. */
export async function devSampleFiles(): Promise<string[]> {
  return json(await fetch("/api/dev/sample-files"));
}

/** Open files picked with the browser's native dialog (multipart). */
export async function uploadFiles(files: FileList | File[]): Promise<ImageMeta[]> {
  const form = new FormData();
  for (const f of Array.from(files)) form.append("files", f, f.name);
  return json(
    await fetch("/api/session/upload", { method: "POST", body: form }),
  );
}

export interface LaunchDir {
  /** Absolute path the app was launched from, or null when none was set. */
  dir: string | null;
  /** Supported image files directly inside that folder. */
  files: { name: string; path: string }[];
}

/** The folder `fermiviewer <dir>` (or the launch cwd) was started in, with
 *  its supported images — lets the in-app Open dialog default there since
 *  the OS-native picker can't be pre-pointed at a directory. */
export async function launchDir(): Promise<LaunchDir> {
  return json(await fetch("/api/session/launch-dir"));
}

/** Supported extensions for the picker's accept filter. */
export async function supportedExtensions(): Promise<string[]> {
  const r = await json<{ extensions: string[] }>(
    await fetch("/api/session/supported-extensions"),
  );
  return r.extensions;
}

export async function closeImage(id: string): Promise<void> {
  await json(await fetch(`/api/image/${id}`, { method: "DELETE" }));
}

export async function fetchHistogram(
  id: string,
  bins = 256,
): Promise<Histogram> {
  return json(await fetch(`/api/image/${id}/histogram?bins=${bins}`));
}

export interface Raster16 {
  data: Uint16Array;
  w: number;
  h: number;
  vmin: number;
  vmax: number;
  /** Total frame count for spectrum_image (3D stack) sources; null otherwise */
  nFrames: number | null;
}

/** Decode a `encode_raster_u16` response (routes/images.py) shared by
 *  `/image/{id}/data16` and the 4D-STEM pattern/nav routes (lib/api/fourd.ts)
 *  — both send pixels the same way, so both decode them the same way. */
export async function decodeRaster16(res: Response): Promise<Raster16> {
  const [h, w] = (res.headers.get("X-Shape") ?? "0,0")
    .split(",")
    .map(Number);
  const vmin = Number(res.headers.get("X-Min") ?? 0);
  const vmax = Number(res.headers.get("X-Max") ?? 1);
  const nFramesHeader = res.headers.get("X-N-Frames");
  const nFrames = nFramesHeader ? Number(nFramesHeader) : null;
  const buf = await res.arrayBuffer();
  return { data: new Uint16Array(buf), w, h, vmin, vmax, nFrames };
}

/** Raw normalized-uint16 raster for the WebGL LUT shader.
 *  For spectrum_image (stack) sources, pass `frame` (0-based) to select a
 *  specific channel; omit to get the energy-summed view. */
export async function fetchData16(id: string, frame?: number): Promise<Raster16> {
  const q = frame != null ? `?frame=${frame}` : "";
  const res = await fetch(`/api/image/${id}/data16${q}`);
  if (!res.ok) throw new Error(`data16 failed: ${res.status}`);
  return decodeRaster16(res);
}

export interface Rgb8 {
  /** Raw uint8 RGB, row-major, length h*w*3. */
  data: Uint8Array;
  w: number;
  h: number;
}

/** Raw colour pixels for an rgb_image — the colour sibling of fetchData16
 *  (ADR 0003 §4). The scalar endpoints 400 for this kind on purpose. */
export async function fetchRgb8(id: string): Promise<Rgb8> {
  const res = await fetch(`/api/image/${id}/rgb8`);
  if (!res.ok) throw new Error(`rgb8 failed: ${res.status}`);
  const [h, w] = (res.headers.get("X-Shape") ?? "0,0,3").split(",").map(Number);
  const buf = await res.arrayBuffer();
  return { data: new Uint8Array(buf), w, h };
}

/** Register a client-composed colour composite as a library image
 *  (ADR 0003 §2: composed once client-side, stored verbatim with the
 *  parent's spatial calibration; the recipe rides along as provenance). */
export async function registerComposite(req: {
  parentId: string;
  name: string;
  width: number;
  height: number;
  /** Raw uint8 RGB, row-major, exactly height*width*3 bytes. */
  pixels: Uint8Array;
  recipe?: Record<string, unknown>;
}): Promise<ImageMeta> {
  // btoa on a binary string — chunked so a large map doesn't blow the
  // argument limit of String.fromCharCode
  let bin = "";
  const CHUNK = 0x8000;
  for (let i = 0; i < req.pixels.length; i += CHUNK) {
    bin += String.fromCharCode(...req.pixels.subarray(i, i + CHUNK));
  }
  return json(
    await fetch("/api/composite/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        parent_id: req.parentId,
        name: req.name,
        width: req.width,
        height: req.height,
        pixels_b64: btoa(bin),
        recipe: req.recipe ?? {},
      }),
    }),
  );
}

export type ProfileReduce = "mean" | "sum";

export interface ProfileResult {
  dist: number[];
  intensity: (number | null)[];
  length: number;
  unit: string;
  reduce: ProfileReduce;
  /** Standard error of the mean per point (ANALYSIS_PRESENTATION_PLAN
   *  item 3) — present only when the profile is a genuine width>1
   *  average (reduce='mean'); absent for width=1, reduce='sum',
   *  polyline profiles, and old cached results. DockPlot shades
   *  intensity ± intensity_sigma when present. */
  intensity_sigma?: (number | null)[];
  /** Present only when the call asked to persist the run (`record`). The
   *  full record arrives on the next project load; this is the handle. */
  result?: CapturedResultRef;
}

/** Line profile. a/b are 0-based image (x, y); backend wants 1-based (row, col). */
export async function measureProfile(
  id: string,
  a: { x: number; y: number },
  b: { x: number; y: number },
  width = 1,
  tilt?: {
    angle: number;
    axis: "X" | "Y";
    geometry: "cross-section" | "surface";
  } | null,
  reduce: ProfileReduce = "mean",
  record = false,
): Promise<ProfileResult> {
  return json(
    await fetch("/api/measure/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        a: [a.y + 1, a.x + 1],
        b: [b.y + 1, b.x + 1],
        width,
        reduce,
        // Persisting is a user decision, not a side effect of every
        // exploratory drag — the flag is only sent when set, so the wire
        // shape is unchanged for the measure-as-you-go path.
        ...(record ? { record: true } : {}),
        // #34: line_profile applies the same tilt correction as
        // measure_distance; 0/absent → off
        ...(tilt && tilt.angle !== 0
          ? {
              tilt_angle_deg: tilt.angle,
              tilt_axis: tilt.axis,
              geometry: tilt.geometry,
            }
          : {}),
      }),
    }),
  );
}

/** Polyline profile through ≥2 vertices (0-based x/y in, 1-based out). */
export async function measurePolyline(
  id: string,
  pts: { x: number; y: number }[],
  width = 1,
  reduce: ProfileReduce = "mean",
  record = false,
): Promise<ProfileResult> {
  return json(
    await fetch("/api/measure/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        points: pts.map((p) => [p.y + 1, p.x + 1]),
        width,
        reduce,
        ...(record ? { record: true } : {}),
      }),
    }),
  );
}

export interface RoiStats {
  mean: number;
  std: number;
  min: number;
  max: number;
  area: number;
  unit: string;
}

/** ROI statistics. Rect corners are 0-based (x, y); backend wants 1-based rows/cols. */
export async function measureRoi(
  id: string,
  a: { x: number; y: number },
  b: { x: number; y: number },
  shape: "rect" | "ellipse" = "rect",
): Promise<RoiStats> {
  return json(
    await fetch("/api/measure/roi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        rect: [
          Math.min(a.y, b.y) + 1,
          Math.min(a.x, b.x) + 1,
          Math.max(a.y, b.y) + 1,
          Math.max(a.x, b.x) + 1,
        ],
        shape,
      }),
    }),
  );
}

export interface BoxProfileResult {
  x_pos: number[]; // pixels, 0-based from the box edge (columns axis)
  x_intensity: (number | null)[];
  y_pos: number[]; // pixels, 0-based from the box edge (rows axis)
  y_intensity: (number | null)[];
  pixel_size: number | null; // unit per px; null = uncalibrated
  unit: string;
  reduce: ProfileReduce;
  rect: [number, number, number, number]; // clamped (row1, col1, row2, col2), 1-based px
}

/** Integrate an axis-aligned box along BOTH axes (item: box-profile CSV).
 *  Corners are 0-based (x, y); backend wants 1-based rows/cols. reduce
 *  defaults to 'sum' — the true integral over the perpendicular extent. */
export async function measureBoxProfile(
  id: string,
  a: { x: number; y: number },
  b: { x: number; y: number },
  reduce: ProfileReduce = "sum",
): Promise<BoxProfileResult> {
  return json(
    await fetch("/api/measure/box-profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        rect: [
          Math.min(a.y, b.y) + 1,
          Math.min(a.x, b.x) + 1,
          Math.max(a.y, b.y) + 1,
          Math.max(a.x, b.x) + 1,
        ],
        reduce,
      }),
    }),
  );
}

// ── analysis (handoff §8, workshops) ────────────────────────────────

export interface Spectrum {
  energy: number[];
  counts: number[];
  units: string;
}

export async function fetchSpectrum(
  id: string,
  region?: [number, number, number, number], // (row0, col0, row1, col1) 1-based
  options?: { signal?: AbortSignal },
): Promise<Spectrum> {
  const q = region
    ? `?row0=${region[0]}&col0=${region[1]}&row1=${region[2]}&col1=${region[3]}`
    : "";
  return json(await fetch(`/api/image/${id}/spectrum${q}`, options));
}
