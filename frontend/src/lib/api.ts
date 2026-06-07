// Typed client for the FastAPI backend (handoff §8). Mirrors the
// Pydantic wire models in src/fermiviewer/models.py — keep in sync.

export type DataKind = "image" | "spectrum" | "spectrum_image";

export interface ImageMeta {
  id: string;
  name: string;
  kind: DataKind;
  shape: number[];
  dtype: string;
  pixel_size: number | null;
  pixel_unit: string;
  n_channels: number | null;
  energy_first: number | null;
  energy_last: number | null;
  energy_units: string;
  meta: Record<string, string | number | boolean>;
}

export interface Histogram {
  bins: number[];
  counts: number[];
}

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export async function openSession(paths: string[]): Promise<ImageMeta[]> {
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
}

/** Raw normalized-uint16 raster for the WebGL LUT shader. */
export async function fetchData16(id: string): Promise<Raster16> {
  const res = await fetch(`/api/image/${id}/data16`);
  if (!res.ok) throw new Error(`data16 failed: ${res.status}`);
  const [h, w] = (res.headers.get("X-Shape") ?? "0,0")
    .split(",")
    .map(Number);
  const vmin = Number(res.headers.get("X-Min") ?? 0);
  const vmax = Number(res.headers.get("X-Max") ?? 1);
  const buf = await res.arrayBuffer();
  return { data: new Uint16Array(buf), w, h, vmin, vmax };
}

export interface ProfileResult {
  dist: number[];
  intensity: (number | null)[];
  length: number;
  unit: string;
}

/** Line profile. a/b are 0-based image (x, y); backend wants 1-based (row, col). */
export async function measureProfile(
  id: string,
  a: { x: number; y: number },
  b: { x: number; y: number },
): Promise<ProfileResult> {
  return json(
    await fetch("/api/measure/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        a: [a.y + 1, a.x + 1],
        b: [b.y + 1, b.x + 1],
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

export async function fetchSpectrum(id: string): Promise<Spectrum> {
  return json(await fetch(`/api/image/${id}/spectrum`));
}

async function post<T>(url: string, body: unknown): Promise<T> {
  return json(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }),
  );
}

export interface EelsBackgroundResult {
  energy: number[];
  spectrum: number[];
  background: number[];
  signal: number[];
  params: Record<string, number>;
}

export function eelsBackground(
  id: string,
  fitWindow: [number, number],
  method = "powerlaw",
): Promise<EelsBackgroundResult> {
  return post("/api/eels/background", {
    image_id: id,
    fit_window: fitWindow,
    method,
  });
}

export function eelsMap(
  id: string,
  signalWindow: [number, number],
  backgroundWindow: [number, number] | null,
  method = "powerlaw",
): Promise<ImageMeta> {
  return post("/api/eels/map", {
    image_id: id,
    signal_window: signalWindow,
    background_window: backgroundWindow,
    method,
  });
}

export interface EelsEdge {
  element: string;
  shell: string;
  z: number;
  onset_ev: number;
  signal_window: [number, number];
  bg_window: [number, number];
}

export interface EelsQuantResult {
  elements: string[];
  atomic_percent: number[];
  intensity: number[];
  sigma: number[];
}

export function eelsQuantify(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
): Promise<EelsQuantResult> {
  return post("/api/eels/quantify", {
    image_id: id,
    edges,
    e0_kv: e0Kv,
    beta_mrad: betaMrad,
  });
}

export interface EdsQuantResult {
  elements: string[];
  lines: string[];
  mean_atomic_pct: number[];
  mean_weight_pct: number[];
  k_factors: number[];
  maps: ImageMeta[];
}

export function edsQuantify(
  id: string,
  elements: string[],
  opts: {
    method?: "cliff-lorimer" | "zaf";
    thicknessNm?: number;
    takeOffAngleDeg?: number;
  } = {},
): Promise<EdsQuantResult> {
  return post("/api/eds/quantify", {
    image_id: id,
    elements,
    method: opts.method ?? "cliff-lorimer",
    thickness_nm: opts.thicknessNm ?? 100,
    take_off_angle_deg: opts.takeOffAngleDeg ?? 20,
  });
}

export interface DetectResult {
  spots: [number, number][]; // 1-based (row, col)
  n: number;
}

export function diffractionDetect(
  id: string,
  opts: { minRadius?: number; threshold?: number; minSeparation?: number } = {},
): Promise<DetectResult> {
  return post("/api/diffraction/detect", {
    image_id: id,
    min_radius: opts.minRadius ?? 10,
    threshold: opts.threshold ?? 0.05,
    min_separation: opts.minSeparation ?? 8,
  });
}

export interface PhaseCandidate {
  phase: string;
  formula: string;
  score: number;
  n_matched: number;
  matched_hkl: number[][];
  zone_axis: number[];
}

export function diffractionIndex(
  id: string,
  spots: [number, number][],
  opts: { pixelSizeMm?: number; cameraLengthMm?: number; accKv?: number } = {},
): Promise<{ candidates: PhaseCandidate[] }> {
  return post("/api/diffraction/index", {
    image_id: id,
    spots,
    pixel_size_mm: opts.pixelSizeMm ?? 1.0,
    camera_length_mm: opts.cameraLengthMm ?? null,
    acc_voltage_kv: opts.accKv ?? 200,
  });
}

/** URL for the windowed 8-bit PNG render (Stage texture + thumbnails). */
export function renderUrl(
  id: string,
  opts: { lo?: number; hi?: number; gamma?: number } = {},
): string {
  const q = new URLSearchParams();
  if (opts.lo !== undefined) q.set("lo", String(opts.lo));
  if (opts.hi !== undefined) q.set("hi", String(opts.hi));
  if (opts.gamma !== undefined) q.set("gamma", String(opts.gamma));
  const qs = q.toString();
  return `/api/image/${id}/render${qs ? `?${qs}` : ""}`;
}
