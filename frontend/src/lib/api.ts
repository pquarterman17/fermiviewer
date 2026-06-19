// Typed client for the FastAPI backend (handoff §8). Mirrors the
// Pydantic wire models in src/fermiviewer/models.py — keep in sync.

import { record, recordPathOp } from "./macro";

export type DataKind = "image" | "spectrum" | "spectrum_image";

export interface ImageMeta {
  id: string;
  name: string;
  kind: DataKind;
  shape: number[];
  dtype: string;
  pixel_size: number | null;
  pixel_unit: string;
  value_unit: string;
  n_channels: number | null;
  energy_first: number | null;
  energy_last: number | null;
  energy_units: string;
  stage_tilt_deg: number | null;
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

/** Raw normalized-uint16 raster for the WebGL LUT shader.
 *  For spectrum_image (stack) sources, pass `frame` (0-based) to select a
 *  specific channel; omit to get the energy-summed view. */
export async function fetchData16(id: string, frame?: number): Promise<Raster16> {
  const q = frame != null ? `?frame=${frame}` : "";
  const res = await fetch(`/api/image/${id}/data16${q}`);
  if (!res.ok) throw new Error(`data16 failed: ${res.status}`);
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

export type ProfileReduce = "mean" | "sum";

export interface ProfileResult {
  dist: number[];
  intensity: (number | null)[];
  length: number;
  unit: string;
  reduce: ProfileReduce;
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
): Promise<Spectrum> {
  const q = region
    ? `?row0=${region[0]}&col0=${region[1]}&row1=${region[2]}&col1=${region[3]}`
    : "";
  return json(await fetch(`/api/image/${id}/spectrum${q}`));
}

async function post<T>(url: string, body: unknown): Promise<T> {
  record(url, body as Record<string, unknown>); // macro capture (no-op
  return json(                                  // unless recording)
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

/** Per-pixel SI composition maps (eelsQuantifyMap — upstream PR #25). */
export function eelsQuantifyMap(
  id: string,
  edges: EelsEdge[],
  e0Kv = 200,
  betaMrad = 10,
): Promise<{
  elements: string[];
  mean_atomic_percent: number[];
  maps: ImageMeta[];
}> {
  return post("/api/eels/quantify-map", {
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

// ── EDS SI explorer ─────────────────────────────────────────────────

export interface EdsLineEnergyResult {
  symbol: string;
  line: "K" | "L" | "M";
  energy_kev: number;
}

/** Snap the energy window to an element's principal X-ray line. */
export async function edsLineEnergy(
  symbol: string,
  beamKv?: number,
): Promise<EdsLineEnergyResult> {
  const q = beamKv != null ? `?beam_kv=${beamKv}` : "";
  return json(await fetch(`/api/eds/line-energy/${encodeURIComponent(symbol)}${q}`));
}

export interface EdsElementMapResult {
  map: number[][];        // H×W float, row-major
  shape: [number, number];
  e_lo: number;
  e_hi: number;
  bg: string;
  total_counts: number;
  map_meta: ImageMeta | null;
}

/** Energy-window integration map for live SI exploration.
 *  bg="linear" subtracts a two-sided background (MATLAB elementMap.m).
 *  saveDerived=true also registers the map as a derived library image. */
export function edsElementMap(
  id: string,
  eLo: number,
  eHi: number,
  opts: {
    bg?: "linear" | "none";
    bgWidth?: number;
    bgGap?: number;
    saveDerived?: boolean;
  } = {},
): Promise<EdsElementMapResult> {
  return post("/api/eds/element-map", {
    image_id: id,
    e_lo: eLo,
    e_hi: eHi,
    bg: opts.bg ?? "linear",
    bg_width: opts.bgWidth ?? NaN,
    bg_gap: opts.bgGap ?? 0,
    save_derived: opts.saveDerived ?? false,
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

/** Analysis region-of-interest — two shapes mirroring the backend _Roi model. */
export type AnalysisRoi =
  | { kind: "rect"; r0: number; c0: number; r1: number; c1: number }
  | { kind: "circle"; cr: number; cc: number; radius: number };

export interface PhaseCandidate {
  phase: string;
  formula: string;
  score: number;
  n_matched: number;
  matched_hkl: number[][];
  matched_d: number[];   // measured d-spacings for each matched spot (Å)
  ref_d: number[];       // reference d-spacings for each matched spot (Å)
  zone_axis: number[];
}

export interface IndexResult {
  center: [number, number];   // [row, col] 1-based pattern centre
  measured_r: number[];       // px radius per spot (same order as input spots)
  candidates: PhaseCandidate[];
}

export function diffractionIndex(
  id: string,
  spots: [number, number][],
  opts: {
    pixelSizeMm?: number;
    cameraLengthMm?: number;
    accKv?: number;
    roi?: AnalysisRoi;
  } = {},
): Promise<IndexResult> {
  return post("/api/diffraction/index", {
    image_id: id,
    spots,
    pixel_size_mm: opts.pixelSizeMm ?? 1.0,
    camera_length_mm: opts.cameraLengthMm ?? null,
    acc_voltage_kv: opts.accKv ?? 200,
    roi: opts.roi ?? null,
  });
}

export function diffractionDetectWithRoi(
  id: string,
  opts: {
    minRadius?: number;
    threshold?: number;
    minSeparation?: number;
    maxSpots?: number;
    roi?: AnalysisRoi;
  } = {},
): Promise<DetectResult> {
  return post("/api/diffraction/detect", {
    image_id: id,
    min_radius: opts.minRadius ?? 10,
    threshold: opts.threshold ?? 0.05,
    min_separation: opts.minSeparation ?? 8,
    max_spots: opts.maxSpots ?? 50,
    roi: opts.roi ?? null,
  });
}

export interface ExportOptions {
  format: "png" | "tiff16" | "jpeg" | "svg" | "pdf";
  scale: number;
  lo: number; // normalized [0,1] window (display state)
  hi: number;
  gamma: number;
  cmap: string;
  include: string[]; // "scale_bar" | "measurements" | "colorbar" | "caption"
  // report caption burned below the figure (WS4c); frontend composes the
  // text (user caption + optional metadata line)
  caption?: string | null;
  measures?: {
    kind: string;
    pts: { x: number; y: number }[];
    text?: string;
    endSymbol?: string;
    width?: number; // box-profile ⊥ averaging width (image px)
  }[];
  overlay_color?: string;
  // custom scale bar geometry (item #33); all optional — null → auto
  scale_bar_norm_x?: number | null;
  scale_bar_norm_y?: number | null;
  scale_bar_length_phys?: number | null;
  scale_bar_thickness?: number | null;
  // tilt correction for distance/profile/polyline labels (#34); 0 → off
  tilt_angle_deg?: number;
  tilt_axis?: "X" | "Y";
  tilt_geometry?: "cross-section" | "surface";
  // scale-bar label font size in screen px (#48); null → 20 (default)
  scale_bar_font_size?: number | null;
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

/** Log-magnitude FFT registered as a derived image. Optional 1-based
 *  rect computes the LOCAL FFT of that region (live-FFT). */
export async function imageFft(
  id: string,
  rect?: [number, number, number, number],
): Promise<ImageMeta> {
  recordPathOp("/api/image/{id}/fft"); // macro capture
  return json(
    await fetch(`/api/image/${id}/fft`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(rect ? { rect } : {}),
    }),
  );
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
  opts: {
    threshold?: number | null;
    minArea?: number;
    watershed?: boolean;
    polarity?: "bright" | "dark";
  },
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
    polarity: opts.polarity ?? "bright",
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

export type GrainMethod = "kmeans" | "gradient" | "rag" | "orientation";

export interface GrainParams {
  method: GrainMethod;
  k?: number;
  granularity?: number;
  compactness?: number;
  orientation_sigma?: number;
  n_superpixels?: number;
  merge_threshold?: number;
  min_area?: number;
}

export interface GrainResult {
  n_grains: number;
  method: GrainMethod;
  labels: ImageMeta;
  mean_diameter_px: number;
  boundary_length_px: number;
  /** true grain-boundary network length (border-excluding inter-grain edges) */
  boundary_network_px: number;
  boundary_length_calibrated: number | null;
  n_boundary_segments: number;
  n_triple_junctions: number;
  /** ASTM E112 grain-size number; null when uncalibrated */
  astm_grain_size: number | null;
  areas_px: number[];
  perimeters_px: number[];
  eccentricity: number[];
  unit: string;
}

export function analyzeGrainsAsync(
  id: string,
  params: GrainParams,
): Promise<{ job_id: string }> {
  return post("/api/analyze/grains", {
    image_id: id,
    run_async: true,
    ...params,
  });
}

export function analyzeGrains(
  id: string,
  params: GrainParams,
): Promise<GrainResult> {
  return post("/api/analyze/grains", { image_id: id, ...params });
}

/** Interactive edit of a grain-label map: merge ≥2 clicked grains, or split
 *  the grain under the (first) click. Returns a fresh, still-editable map. */
export function grainsEdit(
  labelsId: string,
  op: "merge" | "split",
  points: [number, number][],
  granularity = 0.03,
): Promise<GrainResult> {
  return post("/api/grains/edit", {
    labels_id: labelsId,
    op,
    points,
    granularity,
  });
}

// ── user-configurable metadata (custom fields + filename auto-fill) ──────

export interface MetaField {
  name: string;
  type: string;
  options: string[];
}

export interface UserMeta {
  fields: MetaField[];
  patterns: string[];
  config_path: string;
  values: Record<string, string>;
  source_path: string | null;
  can_write_sidecar: boolean;
  has_sidecar: boolean;
}

/** Resolved custom-metadata fields + values for one image (filename →
 *  sidecar → session), plus where they can be persisted. */
export async function getUserMeta(id: string): Promise<UserMeta> {
  return json(await fetch(`/api/image/${id}/usermeta`));
}

/** Persist custom-metadata values to the image + its sidecar (if on disk). */
export function saveUserMeta(
  id: string,
  values: Record<string, string>,
): Promise<{ values: Record<string, string>; wrote_sidecar: boolean }> {
  return post(`/api/image/${id}/usermeta`, { values });
}

export interface BatchAutofillResult {
  results: {
    id: string;
    name: string;
    matched: boolean;
    filled: number;
    wrote_sidecar: boolean;
  }[];
  n_matched: number;
  n_total: number;
}

/** Apply the filename pattern to many images at once, writing each sidecar. */
export function batchAutofill(imageIds: string[]): Promise<BatchAutofillResult> {
  return post("/api/usermeta/batch-autofill", { image_ids: imageIds });
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

/** Headerless RAW import with explicit geometry (checklist L). */
export function openRaw(opts: {
  path: string;
  width: number;
  height: number;
  bitDepth?: number;
  byteOrder?: "little" | "big";
  headerBytes?: number;
}): Promise<ImageMeta> {
  return post("/api/session/open-raw", {
    path: opts.path,
    width: opts.width,
    height: opts.height,
    bit_depth: opts.bitDepth ?? 16,
    byte_order: opts.byteOrder ?? "little",
    header_bytes: opts.headerBytes ?? 0,
  });
}

export function renameImage(id: string, name: string): Promise<ImageMeta> {
  return post(`/api/image/${id}/rename`, { name });
}

/** Multi-panel labeled figure → PNG blob. */
export async function exportFigure(
  ids: string[],
  opts: { cols?: number; gap?: number; scale?: number; cmap?: string } = {},
): Promise<Blob> {
  const res = await fetch("/api/export/figure", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      cols: opts.cols ?? 0,
      gap: opts.gap ?? 4,
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary error body */
    }
    throw new Error(detail);
  }
  return res.blob();
}

/** Auto-detect a burned-in scale bar in the bottom strip. */
export function detectScaleBar(id: string): Promise<{
  found: boolean;
  bar_len: number;
  msg: string;
}> {
  return post("/api/calibration/detect-bar", { image_id: id });
}

/** Explode a 3D cube into per-frame derived images. */
export function explodeStack(id: string): Promise<ImageMeta[]> {
  return post(`/api/image/${id}/explode`, {});
}

export function updateMetadata(
  id: string,
  updates: Record<string, string | number | boolean>,
): Promise<ImageMeta> {
  return post(`/api/image/${id}/metadata`, { updates });
}

/** Render many images server-side into one ZIP. */
export async function exportBatch(
  ids: string[],
  opts: { format?: string; scale?: number; cmap?: string } = {},
): Promise<Blob> {
  const res = await fetch("/api/export/batch", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      format: opts.format ?? "png",
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = ((await res.json()) as { detail?: string }).detail ?? detail;
    } catch {
      /* binary error body */
    }
    throw new Error(detail);
  }
  return res.blob();
}

/** Animate selected images into a GIF; returns the file blob. */
export async function exportGif(
  ids: string[],
  opts: { fps?: number; scale?: number; cmap?: string } = {},
): Promise<{ blob: Blob; filename: string }> {
  const res = await fetch("/api/export/gif", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      image_ids: ids,
      fps: opts.fps ?? 4,
      scale: opts.scale ?? 1,
      cmap: opts.cmap ?? "gray",
    }),
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
  return { blob: await res.blob(), filename: match?.[1] ?? "stack.gif" };
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

// ── structure analysis (atoms / template / CTF / lattice / stitch) ──

export interface PpaStrain {
  valid: boolean;
  exx_mean: number | null;
  eyy_mean: number | null;
  exy_mean: number | null;
  exx: (number | null)[];
  eyy: (number | null)[];
  exy: (number | null)[];
  rotation: (number | null)[];
  displacement: [number, number][];
}

export interface AtomsResult {
  n_columns: number;
  positions: [number, number][]; // (x, y), 1-based
  amplitude: number[];
  converged: boolean[] | null;
  lattice: {
    valid: boolean;
    a1: [number, number] | null;
    a2: [number, number] | null;
    spacing: number | null;
  };
  sublattice?: number[];
  strain?: PpaStrain;
  /** median R² across converged fits (set by UI from fit.rsquared) */
  mean_rsq?: number;
}

export function analyzeAtoms(
  id: string,
  opts: {
    sigma?: number;
    threshold?: number;
    minSeparation?: number;
    winRadius?: number;
    polarity?: "bright" | "dark";
    refine?: boolean;
    sublattices?: number;
    strain?: boolean;
  } = {},
): Promise<AtomsResult> {
  return post("/api/analyze/atoms", {
    image_id: id,
    sigma: opts.sigma ?? 2,
    threshold: opts.threshold ?? 0.2,
    min_separation: opts.minSeparation ?? 8,
    win_radius: opts.winRadius ?? 6,
    polarity: opts.polarity ?? "bright",
    refine: opts.refine ?? true,
    sublattices: opts.sublattices ?? 1,
    strain: opts.strain ?? false,
  });
}

export function analyzeAtomsStrain(
  positions: [number, number][],
  opts: {
    refVectors?: [[number, number], [number, number]];
    origin?: [number, number];
    neighbors?: number;
  } = {},
): Promise<PpaStrain> {
  return post("/api/atoms/strain", {
    positions,
    ref_vectors: opts.refVectors ?? null,
    origin: opts.origin ?? null,
    neighbors: opts.neighbors ?? 8,
  });
}

export function atomsExportCsv(
  positions: [number, number][],
  amplitude: number[],
  sublattice: number[] | undefined,
  strain: PpaStrain | undefined,
): string {
  const header = "x_px,y_px,amplitude,sublattice,exx,eyy,exy,rotation_rad";
  const rows = positions.map(([x, y], i) => {
    const amp = amplitude[i] ?? "";
    const sub = sublattice ? (sublattice[i] ?? "") : "";
    const exx = strain?.exx[i] ?? "";
    const eyy = strain?.eyy[i] ?? "";
    const exy = strain?.exy[i] ?? "";
    const rot = strain?.rotation[i] ?? "";
    return `${x.toFixed(4)},${y.toFixed(4)},${amp},${sub},${exx},${eyy},${exy},${rot}`;
  });
  return [header, ...rows].join("\n");
}

export function analyzeTemplate(
  id: string,
  rect: [number, number, number, number], // (row, col, h, w) 1-based
  threshold = 0.7,
): Promise<{
  n_matches: number;
  locations: [number, number][]; // (row, col) centres
  scores: number[];
}> {
  return post("/api/analyze/template-match", {
    image_id: id,
    rect,
    threshold,
  });
}

export function analyzeStitch(
  ids: string[],
  opts: { layout?: string; overlapFrac?: number } = {},
): Promise<{ mosaic: ImageMeta; offsets: number[][]; layout: string }> {
  return post("/api/analyze/stitch", {
    image_ids: ids,
    layout: opts.layout ?? "horizontal",
    overlap_frac: opts.overlapFrac ?? 0.2,
  });
}

export interface CtfResult {
  defocus_a: number;
  defocus_nm: number;
  r_squared: number;
  lambda_a: number;
  radial_freq: number[];
  radial_power: number[];
  ctf_fit: number[];
}

export function analyzeCtf(
  id: string,
  opts: { voltageKv?: number; csMm?: number; pixelSizeA?: number } = {},
): Promise<CtfResult> {
  return post("/api/analyze/ctf", {
    image_id: id,
    voltage_kv: opts.voltageKv ?? 200,
    cs_mm: opts.csMm ?? 1.2,
    pixel_size_a: opts.pixelSizeA ?? 1,
  });
}

export function analyzeInterfaceWidth(
  x: number[],
  y: (number | null)[],
  model: "erf" | "sigmoid" = "erf",
): Promise<{
  center: number;
  sigma: number;
  width_10_90: number;
  r_squared: number;
}> {
  return post("/api/analyze/interface-width", {
    x,
    y: y.map((v) => v ?? 0),
    model,
  });
}

export function analyzeNoise(id: string): Promise<{
  sigma: number;
  snr_db: number;
  noise_type: string;
  recommendation: string;
}> {
  return post("/api/analyze/noise", { image_id: id });
}

export function analyzeDefects(id: string): Promise<{
  intersections: number;
  test_lines: number;
  density: number;
  density_unit: string;
  enhanced: ImageMeta;
}> {
  return post("/api/analyze/defects", { image_id: id });
}

export function analyzeImageMath(
  aId: string,
  bId: string,
  op: "subtract" | "divide" | "ratio" | "add",
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/image-math", { a_id: aId, b_id: bId, op });
}

export function analyzeAlignStack(
  ids: string[],
): Promise<{ images: ImageMeta[]; shifts: number[][] }> {
  return post("/api/analyze/align-stack", { image_ids: ids });
}

export function analyzeMip(ids: string[]): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/mip", { image_ids: ids });
}

export function analyzeLattice(
  id: string,
  spot1: [number, number], // (row, col) 1-based on the FFT image
  spot2: [number, number],
): Promise<{
  a: number;
  b: number;
  gamma_deg: number;
  d_spacing1: number;
  d_spacing2: number;
  unit_cell_area: number;
  unit: string;
}> {
  return post("/api/analyze/lattice", { image_id: id, spot1, spot2 });
}

// ── A3 Back Project ─────────────────────────────────────────────────

export function analyzeBackProject(
  id: string,
  filter: "ramp" | "shepp-logan" | "hamming" | "none" = "ramp",
  outputSize = 0,
): Promise<ImageMeta> {
  return post("/api/analyze/back-project", {
    image_id: id,
    filter,
    output_size: outputSize,
  });
}

// ── A4 Composition Profile ───────────────────────────────────────────

export interface CompositionProfileResult {
  distance: number[];
  atomic_pct: number[][];   // [n_elements][n_points]
  elements: string[];
  unit: string;
}

export function analyzeCompositionProfile(
  mapIds: string[],
  elements: string[],
  a: { x: number; y: number },
  b: { x: number; y: number },
  opts: { nPoints?: number; width?: number } = {},
): Promise<CompositionProfileResult> {
  return post("/api/analyze/composition-profile", {
    image_id: mapIds[0] ?? "",
    map_ids: mapIds,
    elements,
    x1: a.x + 1,   // 0-based → 1-based
    y1: a.y + 1,
    x2: b.x + 1,
    y2: b.y + 1,
    n_points: opts.nPoints ?? 200,
    width: opts.width ?? 1,
  });
}

// ── A5 ELNES ────────────────────────────────────────────────────────

export interface ElnesResult {
  relative_energy: number[];
  intensity: number[];
  edge_jump: number;
  edge_onset: number;
  background_params: Record<string, number>;
  reference_energy?: number[];
  reference_intensity?: number[];
}

export function analyzeElnes(
  id: string,
  edgeOnset: number,
  fitWindow: [number, number],
  opts: {
    elnesWindow?: [number, number];
    method?: string;
    normalize?: boolean;
    referenceId?: string;
  } = {},
): Promise<ElnesResult> {
  return post("/api/analyze/elnes", {
    image_id: id,
    edge_onset: edgeOnset,
    fit_window: fitWindow,
    elnes_window: opts.elnesWindow ?? [0, 30],
    method: opts.method ?? "powerlaw",
    normalize: opts.normalize ?? true,
    reference_id: opts.referenceId ?? null,
  });
}

// ── A8 Simulate + phase list ─────────────────────────────────────────

export interface PhaseInfo {
  name: string;
  formula: string;
  category: string;
}

export async function listDiffractionPhases(): Promise<PhaseInfo[]> {
  const r = await json<{ phases: PhaseInfo[] }>(
    await fetch("/api/diffraction/phases"),
  );
  return r.phases;
}

export interface SimSpot {
  hkl: [number, number, number];
  d_spacing: number | null;
  intensity: number;
  row: number;
  col: number;
}

export interface SimulateResult {
  phase: string;
  formula: string;
  zone_axis: [number, number, number];
  lam_angstrom: number;
  spots: SimSpot[];
  image: ImageMeta | null;
}

export function analyzeDiffractionSimulate(
  phaseName: string,
  zoneAxis: [number, number, number],
  opts: {
    accVoltage?: number;
    cameraLength?: number;
    pixelSize?: number;
    imageSize?: [number, number];
    parentImageId?: string;
  } = {},
): Promise<SimulateResult> {
  return post("/api/analyze/simulate", {
    phase_name: phaseName,
    zone_axis: zoneAxis,
    acc_voltage: opts.accVoltage ?? 200,
    camera_length: opts.cameraLength ?? 200,
    pixel_size: opts.pixelSize ?? 0.05,
    image_size: opts.imageSize ?? [512, 512],
    parent_image_id: opts.parentImageId ?? null,
  });
}

// ── A44 EDS auto-assign ──────────────────────────────────────────────

export interface EdsAutoAssignResult {
  peaks_kev: number[];
  assignments: { peak_kev: number; candidates: { symbol: string; line: string; energy_kev: number; delta_kev: number }[] }[];
}

export function edsAutoAssign(
  id: string,
  opts: { toleranceKev?: number; threshold?: number } = {},
): Promise<EdsAutoAssignResult> {
  return post("/api/eds/auto-assign", {
    image_id: id,
    tolerance_kev: opts.toleranceKev ?? 0.15,
    threshold: opts.threshold ?? 0.05,
  });
}

// ── #34 Tilt-corrected distance ──────────────────────────────────────

export interface TiltDistanceResult {
  raw_px: number;
  raw_calibrated: number | null;
  corrected_px: number;
  corrected_calibrated: number | null;
  unit: string;
  tilt_angle_deg: number;
  tilt_axis: string;
  geometry: string;
}

export function measureDistanceTilted(
  id: string,
  x1: number, y1: number,
  x2: number, y2: number,
  opts: {
    tiltAngleDeg?: number;
    tiltAxis?: "X" | "Y";
    geometry?: "cross-section" | "surface";
  } = {},
): Promise<TiltDistanceResult> {
  return post("/api/measure/distance-tilted", {
    image_id: id,
    x1: x1 + 1, y1: y1 + 1,
    x2: x2 + 1, y2: y2 + 1,
    tilt_angle_deg: opts.tiltAngleDeg ?? 0,
    tilt_axis: opts.tiltAxis ?? "Y",
    geometry: opts.geometry ?? "cross-section",
  });
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

// ── named workspaces (design WS4b) ──────────────────────────────────
// A workspace is the same session payload, addressed by display name and
// kept under the OS config dir instead of a user-typed path.

export interface WorkspaceInfo {
  slug: string;
  name: string;
  saved_at: string | null;
  n_images: number;
}

export async function listWorkspaces(): Promise<WorkspaceInfo[]> {
  const r = await json<{ workspaces: WorkspaceInfo[] }>(
    await fetch("/api/workspaces"),
  );
  return r.workspaces;
}

export async function saveWorkspaceNamed(
  name: string,
  clientState: SessionClientState,
): Promise<{ slug: string; name: string; n_images: number }> {
  return post("/api/workspaces/save", { name, client_state: clientState });
}

export async function loadWorkspaceNamed(slug: string): Promise<{
  images: ImageMeta[];
  client_state: SessionClientState | null;
  name: string;
}> {
  return post("/api/workspaces/load", { slug });
}

export async function deleteWorkspace(
  slug: string,
): Promise<{ deleted: boolean }> {
  return json(await fetch(`/api/workspaces/${slug}`, { method: "DELETE" }));
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
