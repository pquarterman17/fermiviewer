// Extracted from lib/api.ts; public imports remain stable via the barrel.
import type { ImageMeta } from "./core";
import { json, post } from "./transport";

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

export interface MontageOptions {
  cols?: number | null;
  labels?: boolean;
  gap?: number;
  bg?: number;
  overlap?: number;
  font_size?: number;
}

export function analyzeMontage(
  ids: string[],
  opts: MontageOptions = {},
): Promise<{ image: ImageMeta }> {
  return post("/api/analyze/montage", {
    image_ids: ids,
    cols: opts.cols ?? null,
    labels: opts.labels ?? true,
    gap: opts.gap ?? 4,
    bg: opts.bg ?? 0,
    overlap: opts.overlap ?? 0,
    font_size: opts.font_size ?? 14,
  });
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
  custom?: boolean; // imported/CIF phase (vs built-in database)
}

export async function listDiffractionPhases(): Promise<PhaseInfo[]> {
  const r = await json<{ phases: PhaseInfo[] }>(
    await fetch("/api/diffraction/phases"),
  );
  return r.phases;
}

/** Import a custom phase from CIF text (Diffraction #2). */
export function importDiffractionPhase(
  cifText: string,
  name = "",
): Promise<{ name: string; formula: string; centering: string; system: string; n_sites: number }> {
  return post("/api/diffraction/phases/import", { cif_text: cifText, name });
}

/** Delete a custom phase by name (built-ins are protected server-side). */
export async function deleteDiffractionPhase(name: string): Promise<void> {
  await json(
    await fetch(`/api/diffraction/phases/${encodeURIComponent(name)}`, {
      method: "DELETE",
    }),
  );
}

export interface CalibrationResult {
  ellipse: {
    center_row: number;
    center_col: number;
    a: number;
    b: number;
    theta_deg: number;
    eccentricity: number;
    mean_radius: number;
  };
  n_points: number;
  rms_residual_px: number;
  d_known_ang: number | null;
  camera_constant_px_ang: number | null;
}

/** Fit an ellipse to the dominant ring + anchor the camera constant
 *  (Diffraction #1). Supply either a known d-spacing or a standard phase+hkl. */
export function diffractionCalibrate(
  imageId: string,
  opts: {
    dKnownAng?: number;
    standardPhase?: string;
    hkl?: [number, number, number];
    rMin?: number;
    rMax?: number;
  } = {},
): Promise<CalibrationResult> {
  return post("/api/diffraction/calibrate", {
    image_id: imageId,
    d_known_ang: opts.dKnownAng ?? null,
    standard_phase: opts.standardPhase ?? null,
    hkl: opts.hkl ?? null,
    r_min: opts.rMin ?? 5,
    r_max: opts.rMax ?? null,
  });
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
    scatteringModel?: "fe" | "z";
    debyeWallerB?: number | null;
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
    scattering_model: opts.scatteringModel ?? "fe",
    debye_waller_B: opts.debyeWallerB ?? null,
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
