import type { ImageMeta } from "./api";

export type SpectralModality = "eels" | "eds";
export type SpectralClassification = {
  modality: SpectralModality | null;
  reason: string;
};

const STORAGE_KEY = "fv_spectral_modalities";

function storedChoices(): Record<string, SpectralModality> {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "{}");
    return parsed && typeof parsed === "object"
      ? (parsed as Record<string, SpectralModality>)
      : {};
  } catch {
    return {};
  }
}

export function spectralDatasetKey(meta: ImageMeta): string {
  const source =
    typeof meta.meta.source === "string" ? meta.meta.source : meta.name;
  return [
    source,
    meta.shape.join("x"),
    meta.energy_first ?? "",
    meta.energy_last ?? "",
    meta.energy_units,
  ].join("|");
}

export function loadSpectralModality(
  meta: ImageMeta,
): SpectralModality | null {
  const value = storedChoices()[spectralDatasetKey(meta)];
  return value === "eels" || value === "eds" ? value : null;
}

export function saveSpectralModality(
  meta: ImageMeta,
  modality: SpectralModality,
): void {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...storedChoices(),
        [spectralDatasetKey(meta)]: modality,
      }),
    );
  } catch {
    // Storage failure must not prevent opening a workspace.
  }
}

function tokenModality(text: string): SpectralModality | null {
  const hasEels = /(?:^|[^a-z])eels(?:[^a-z]|$)/i.test(text);
  const hasEds = /(?:^|[^a-z])eds(?:[^a-z]|$)/i.test(text);
  if (hasEels === hasEds) return null;
  return hasEels ? "eels" : "eds";
}

function energyRangeEv(meta: ImageMeta): [number, number] | null {
  if (meta.energy_first === null || meta.energy_last === null) return null;
  const unit = meta.energy_units.trim().toLowerCase();
  const factor = unit === "kev" ? 1000 : unit === "ev" ? 1 : null;
  if (factor === null) return null;
  const a = meta.energy_first * factor;
  const b = meta.energy_last * factor;
  return [Math.min(a, b), Math.max(a, b)];
}

/** Conservative routing: strong evidence opens directly; ambiguous cubes ask. */
export function classifySpectralModality(
  meta: ImageMeta,
): SpectralClassification {
  const explicitKeys = [
    "signal_type",
    "signalType",
    "spectrum_type",
    "modality",
    "acquisition_mode",
  ];
  for (const key of explicitKeys) {
    const value = meta.meta[key];
    if (typeof value !== "string") continue;
    const modality = tokenModality(value);
    if (modality) return { modality, reason: `${key} metadata` };
  }

  const source =
    typeof meta.meta.source === "string" ? meta.meta.source : meta.name;
  const named = tokenModality(`${meta.name} ${source}`);
  if (named) return { modality: named, reason: "dataset name" };

  if (String(meta.meta.parser).toLowerCase() === "bcf") {
    return { modality: "eds", reason: "Bruker BCF format" };
  }

  const range = energyRangeEv(meta);
  if (range) {
    const [lo, hi] = range;
    const span = hi - lo;
    if (hi >= 5000 && lo <= 1000 && span >= 3000) {
      return { modality: "eds", reason: "broad X-ray energy range" };
    }
    if (lo < -5 || (lo >= 100 && hi <= 3000 && span <= 2500)) {
      return { modality: "eels", reason: "loss-energy range" };
    }
  }

  return {
    modality: null,
    reason: "the file does not contain a decisive EELS/EDS signal",
  };
}

export function resolveSpectralModality(
  meta: ImageMeta,
): SpectralClassification {
  const stored = loadSpectralModality(meta);
  return stored
    ? { modality: stored, reason: "saved choice" }
    : classifySpectralModality(meta);
}
