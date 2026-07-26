import type { Spectrum } from "./api";

/** EDS controls and line libraries use keV, while several file formats
 * expose an otherwise-valid spectral calibration in eV. Keep the source
 * response immutable and normalize only the EDS presentation layer. */
export function normalizeEdsSpectrum(spec: Spectrum): Spectrum {
  const unit = spec.units.trim().toLowerCase();
  if (unit === "ev") {
    return {
      ...spec,
      energy: spec.energy.map((value) => value / 1000),
      units: "keV",
    };
  }
  if (unit === "kev" && spec.units !== "keV") {
    return { ...spec, units: "keV" };
  }
  return spec;
}

function scaled(value: number, divisor: number, suffix: string): string {
  const magnitude = Math.abs(value / divisor);
  const digits = magnitude >= 100 ? 0 : magnitude >= 10 ? 1 : 2;
  return `${Number((value / divisor).toFixed(digits))}${suffix}`;
}

/** Short labels prevent full-cube totals from overflowing uPlot's y gutter. */
export function formatCountTick(value: number): string {
  if (!Number.isFinite(value)) return "—";
  const magnitude = Math.abs(value);
  if (magnitude >= 1e12) return scaled(value, 1e12, "T");
  if (magnitude >= 1e9) return scaled(value, 1e9, "G");
  if (magnitude >= 1e6) return scaled(value, 1e6, "M");
  if (magnitude >= 1e3) return scaled(value, 1e3, "k");
  return Number(value.toFixed(magnitude < 10 ? 2 : 0)).toString();
}
