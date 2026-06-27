/**
 * Format a quantity with its 1σ uncertainty as "value ± error".
 *
 * Used by the EELS/EDS composition tables (PLAN_SPECTRAL_QUANT #6). The
 * number of decimals tracks the error so the ± term shows ~1–2 significant
 * figures (capped at 3 decimals); both value and error share that precision.
 * A non-finite value renders as an em dash; a zero / non-finite / negative
 * error (e.g. a single-element composition, which has no compositional
 * freedom) renders the value alone.
 */
export function formatPlusMinus(
  value: number,
  error: number,
  digits = 1,
): string {
  if (!Number.isFinite(value)) return "—";
  if (!Number.isFinite(error) || error <= 0) return value.toFixed(digits);
  const decimals = Math.min(3, Math.max(digits, 1 - Math.floor(Math.log10(error))));
  return `${value.toFixed(decimals)} ± ${error.toFixed(decimals)}`;
}
