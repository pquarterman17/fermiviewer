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

/** Open files picked with the browser's native dialog (multipart). */
export async function uploadFiles(files: FileList | File[]): Promise<ImageMeta[]> {
  const form = new FormData();
  for (const f of Array.from(files)) form.append("files", f, f.name);
  return json(
    await fetch("/api/session/upload", { method: "POST", body: form }),
  );
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
  width = 1,
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
      }),
    }),
  );
}

/** Polyline profile through ≥2 vertices (0-based x/y in, 1-based out). */
export async function measurePolyline(
  id: string,
  pts: { x: number; y: number }[],
  width = 1,
): Promise<ProfileResult> {
  return json(
    await fetch("/api/measure/profile", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        image_id: id,
        points: pts.map((p) => [p.y + 1, p.x + 1]),
        width,
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

// ── EELS advanced (thickness / KK / Fourier-log / SVD / align) ──────

export function eelsThickness(
  id: string,
  zlpWindow: [number, number] = [-5, 5],
): Promise<{
  map: ImageMeta;
  mean_t_over_lambda: number;
  valid_fraction: number;
}> {
  return post("/api/eels/thickness", { image_id: id, zlp_window: zlpWindow });
}

export interface KKResult {
  energy: number[];
  eps1: number[];
  eps2: number[];
  elf: number[];
  optical_conductivity: number[];
  refractive_index: number[];
  thickness_nm: number;
  t_over_lambda: number;
}

export function eelsKK(
  id: string,
  opts: {
    zlpWindow?: [number, number];
    refractiveIndex?: number;
    accKv?: number;
  } = {},
): Promise<KKResult> {
  return post("/api/eels/kk", {
    image_id: id,
    zlp_window: opts.zlpWindow ?? [-5, 5],
    refractive_index: opts.refractiveIndex ?? null,
    acc_voltage_kv: opts.accKv ?? 200,
  });
}

export function eelsFourierLog(
  id: string,
  zlpWindow: [number, number] = [-5, 5],
): Promise<{
  energy: number[];
  spectrum: number[];
  ssd: number[];
  t_over_lambda: number;
}> {
  return post("/api/eels/fourier-log", {
    image_id: id,
    zlp_window: zlpWindow,
  });
}

export function eelsSvd(
  id: string,
  opts: { nComponents?: number; denoise?: boolean; nScoreMaps?: number } = {},
): Promise<{
  explained: number[];
  cumulative: number[];
  energy: number[];
  eigenspectra: number[][];
  score_maps: ImageMeta[];
  denoised?: ImageMeta;
}> {
  return post("/api/eels/svd", {
    image_id: id,
    n_components: opts.nComponents ?? 0,
    denoise: opts.denoise ?? false,
    n_score_maps: opts.nScoreMaps ?? 4,
  });
}

export function eelsAlignZlp(
  id: string,
  window: [number, number] = [-20, 20],
): Promise<{
  aligned: ImageMeta;
  max_shift: number;
  shifted_fraction: number;
}> {
  return post("/api/eels/align-zlp", { image_id: id, window });
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

export interface ExportOptions {
  format: "png" | "tiff16" | "jpeg" | "svg" | "pdf";
  scale: number;
  lo: number; // normalized [0,1] window (display state)
  hi: number;
  gamma: number;
  cmap: string;
  include: string[]; // "scale_bar" | "measurements"
  measures?: {
    kind: string;
    pts: { x: number; y: number }[];
    text?: string;
  }[];
  overlay_color?: string;
}

/** Server-side export; returns the file blob + suggested filename. */
export async function exportImage(
  id: string,
  opts: ExportOptions,
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch("/api/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ image_id: id, ...opts }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary or empty error body */
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = /filename="([^"]+)"/.exec(disposition);
  return {
    blob: await res.blob(),
    filename: match?.[1] ?? `export.${opts.format === "tiff16" ? "tif" : opts.format}`,
  };
}

// ── item-28 analysis surface ────────────────────────────────────────

/** Apply a server-side filter; returns the derived image's meta. */
export function applyFilter(
  id: string,
  kind: string,
  params: Record<string, unknown> = {},
): Promise<ImageMeta> {
  return post("/api/filter", { image_id: id, kind, params });
}

/** Log-magnitude FFT registered as a derived image. */
export async function imageFft(id: string): Promise<ImageMeta> {
  return json(await fetch(`/api/image/${id}/fft`, { method: "POST" }));
}

/** Masked-FFT inverse (Fourier filter). Masks are (row, col, radius)
 *  in 1-based FFT pixels; the backend mirrors conjugate-symmetric
 *  partners. Returns the filtered real-space derived image. */
export function analyzeFftMask(
  id: string,
  masks: [number, number, number][],
  mode: "pass" | "reject",
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/fft-mask", { image_id: id, masks, mode });
}

export function analyzeRadial(
  id: string,
  opts: {
    azimuthal?: boolean;
    sectorMin?: number;
    sectorMax?: number;
  } = {},
): Promise<{
  radii: number[];
  intensity: (number | null)[];
  unit: string;
}> {
  return post("/api/analyze/radial", {
    image_id: id,
    azimuthal: opts.azimuthal ?? false,
    sector_min: opts.sectorMin ?? 0,
    sector_max: opts.sectorMax ?? 360,
  });
}

export function analyzeVdf(
  id: string,
  center: [number, number],
  radius: number,
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/vdf", { image_id: id, center, radius });
}

export function analyzeGpa(
  id: string,
  g1: [number, number],
  g2: [number, number],
): Promise<{ maps: ImageMeta[]; mean: Record<string, number> }> {
  return post("/api/analyze/gpa", { image_id: id, g1, g2 });
}

export interface ParticleRow {
  id: number;
  area: number;
  centroid: [number, number];
  equiv_diameter: number;
  mean_intensity: number;
  area_calibrated: number | null;
  diameter_calibrated: number | null;
}

export function analyzeParticles(
  id: string,
  opts: { threshold?: number | null; minArea?: number; watershed?: boolean },
): Promise<{
  n_particles: number;
  threshold: number;
  labels: ImageMeta;
  particles: ParticleRow[];
  unit: string;
}> {
  return post("/api/analyze/particles", {
    image_id: id,
    threshold: opts.threshold ?? null,
    min_area: opts.minArea ?? 1,
    use_watershed: opts.watershed ?? false,
  });
}

export interface JobStatus {
  id: string;
  status: "running" | "done" | "error";
  progress: number;
  message: string;
  result?: unknown;
  error?: string;
}

/** Start an async job; poll until done; reports progress via callback. */
export async function runJob<T>(
  start: () => Promise<{ job_id: string }>,
  onProgress: (fraction: number, message: string) => void,
  pollMs = 400,
): Promise<T> {
  const { job_id } = await start();
  for (;;) {
    const s = await json<JobStatus>(await fetch(`/api/jobs/${job_id}`));
    if (s.status === "done") return s.result as T;
    if (s.status === "error") throw new Error(s.error ?? "job failed");
    onProgress(s.progress, s.message);
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

export function analyzeGrainsAsync(
  id: string,
  k: number,
): Promise<{ job_id: string }> {
  return post("/api/analyze/grains", { image_id: id, k, run_async: true });
}

export function analyzeGrains(
  id: string,
  k: number,
): Promise<{
  n_grains: number;
  labels: ImageMeta;
  mean_diameter_px: number;
  areas_px: number[];
  boundary_length_px: number;
  unit: string;
}> {
  return post("/api/analyze/grains", { image_id: id, k });
}

export function analyzeRoughness(
  id: string,
): Promise<Record<string, number | string>> {
  return post("/api/analyze/roughness", { image_id: id });
}

export function applyCalibration(
  id: string,
  pixelSize: number,
  unit: string,
  saveAsKey?: string,
): Promise<{ image: ImageMeta }> {
  return post("/api/calibration/apply", {
    image_id: id,
    pixel_size: pixelSize,
    unit,
    save_as_key: saveAsKey || null,
  });
}

export interface CalibrationEntry {
  pixel_size: number;
  unit: string;
  note: string;
  saved: string;
}

export async function listCalibrations(): Promise<
  Record<string, CalibrationEntry>
> {
  const r = await fetch("/api/calibration");
  if (!r.ok) throw new Error(`calibration list failed: ${r.status}`);
  return ((await r.json()) as { entries: Record<string, CalibrationEntry> })
    .entries;
}

export async function deleteCalibration(key: string): Promise<void> {
  const r = await fetch(`/api/calibration/${encodeURIComponent(key)}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error(`calibration delete failed: ${r.status}`);
}

/** Apply a STORED calibration (by key) to an image. */
export function applyCalibrationKey(
  id: string,
  key: string,
): Promise<{ image: ImageMeta }> {
  return post("/api/calibration/apply", { image_id: id, key });
}

// ── workspace persistence ───────────────────────────────────────────

export interface SessionClientState {
  order?: string[];
  activeId?: string | null;
  views?: Record<string, unknown>;
  display?: Record<string, unknown>;
  measures?: Record<string, unknown>;
  overlay?: unknown;
}

export async function saveSession(
  path: string,
  clientState: SessionClientState,
): Promise<{ n_images: number; json_path: string }> {
  return post("/api/session/save", { path, client_state: clientState });
}

export async function loadSession(
  path: string,
): Promise<{ images: ImageMeta[]; client_state: SessionClientState | null }> {
  return post("/api/session/load", { path });
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
