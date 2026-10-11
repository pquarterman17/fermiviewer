import type { ImageMeta, Spectrum } from "../api";
import { clampRange, type XRange } from "./zoomRange";

const SIGNAL_FRACTION = 0.995;
const CONTEXT_CHANNELS = 8;

function finitePositive(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
}

/** Beam energy recorded by the file parser, expressed in keV. */
export function metadataBeamEnergyKev(meta: ImageMeta | null): number | null {
  if (!meta) return null;
  const direct = finitePositive(meta.meta.beam_kv ?? meta.meta.voltage_kV);
  if (direct !== null) return direct;
  const volts = finitePositive(meta.meta.acceleration_voltage_v);
  return volts === null ? null : volts / 1000;
}

function quantile(values: number[], fraction: number): number {
  if (values.length === 0) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor((sorted.length - 1) * fraction)] ?? 0;
}

/**
 * Return a readable initial EDS viewport, or null when the acquired axis is
 * already the useful view. Counts below the robust tail baseline do not make
 * a long detector tail look occupied. A small context margin keeps the last
 * line away from the plot edge.
 */
export function usefulSpectrumRange(
  spectrum: Spectrum,
  beamEnergyKev: number | null = null,
): XRange | null {
  const n = Math.min(spectrum.energy.length, spectrum.counts.length);
  if (n < 2) return null;

  const full: XRange = [spectrum.energy[0]!, spectrum.energy[n - 1]!];
  if (!Number.isFinite(full[0]) || !Number.isFinite(full[1]) || full[1] <= full[0]) {
    return null;
  }
  const channel = (full[1] - full[0]) / (n - 1);
  const lower = Math.min(full[1], Math.max(full[0], 0));
  const beamLimit = beamEnergyKev && beamEnergyKev > lower
    ? Math.min(full[1], beamEnergyKev)
    : full[1];

  const eligible: number[] = [];
  const eligibleIndices: number[] = [];
  for (let i = 0; i < n; i += 1) {
    const energy = spectrum.energy[i]!;
    if (energy < lower || energy > beamLimit) continue;
    eligibleIndices.push(i);
    const count = spectrum.counts[i]!;
    eligible.push(Number.isFinite(count) ? Math.max(0, count) : 0);
  }
  if (eligible.length < 2) return null;

  // The lower 60% is resistant to peaks and represents the empty-tail floor
  // for ordinary EDS spectra. MAD supplies a noise-aware significance test.
  const baseline = quantile(eligible, 0.6);
  const deviations = eligible.map((value) => Math.abs(value - baseline));
  const mad = quantile(deviations, 0.5);
  const peak = Math.max(...eligible);
  const threshold = baseline + Math.max(6 * mad, 5 * Math.sqrt(baseline), peak * 0.002);
  const excess = eligible.map((value) => Math.max(0, value - baseline));
  const excessTotal = excess.reduce((sum, value) => sum + value, 0);

  let lastLocal = eligible.length - 1;
  if (excessTotal > 0) {
    let cumulative = 0;
    const target = excessTotal * SIGNAL_FRACTION;
    lastLocal = 0;
    for (let i = 0; i < excess.length; i += 1) {
      cumulative += excess[i]!;
      if (cumulative >= target) {
        lastLocal = i;
        break;
      }
    }
    for (let i = eligible.length - 1; i >= 0; i -= 1) {
      if (eligible[i]! >= threshold) {
        lastLocal = Math.max(lastLocal, i);
        break;
      }
    }
  }

  const lastIndex = eligibleIndices[Math.min(
    eligible.length - 1,
    lastLocal + CONTEXT_CHANNELS,
  )]!;
  const upper = Math.min(beamLimit, spectrum.energy[lastIndex]!);
  const candidate = clampRange([lower, upper], full, channel * 6);
  if (candidate === null) return null;
  const tolerance = channel * 0.5;
  return candidate[0] <= full[0] + tolerance && candidate[1] >= full[1] - tolerance
    ? null
    : candidate;
}
