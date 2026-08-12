// Fit-quality helpers for the EELS/EDS model-fit views (audit R4 / #2:
// ANALYSIS_PRESENTATION_PLAN.md item 2 "surface residuals + R² on
// existing fits"). Both /eels/fit and /eds/peakfit already return the
// measured spectrum ("spectrum") and the fitted curve ("model") over the
// SAME axis, so deriving the residual trace client-side is the thinnest
// correct path — serialising a third array over the wire would be a pure
// duplicate of `spectrum` and `model`, which are already there.
//
// `rSquared` is NOT how the R² shown in the UI is computed — that comes
// straight from the backend's `r_squared` field (calc/fit_quality.py),
// because the backend knows the ACTUAL fit window (e.g. EELS's
// `fit_range`), which can be a strict subset of the energy axis returned
// for plotting. Calling this on the full display axis would silently
// answer a different question ("how well does the fit extrapolate over
// the whole plot" rather than "how well did the fit explain what it was
// fit to"). It is exported and tested here anyway because it is the same
// pure formula the backend uses (`1 − SS_res/SS_tot`, plain and
// unweighted) — useful for any future client-only computation, and its
// own contract (in particular the degenerate SS_tot=0 case) is worth
// pinning with a test independent of a network round trip.

/** Point-wise "observed − model", the plotting convention (positive means
 *  the data sits above the fit). Throws on a length mismatch rather than
 *  silently truncating/padding — a shape mismatch means the caller passed
 *  two curves that were never fit against each other. */
export function residual(actual: number[], model: number[]): number[] {
  if (actual.length !== model.length) {
    throw new Error(
      `residual: actual (${actual.length}) and model (${model.length}) must be the same length`,
    );
  }
  return actual.map((a, i) => a - model[i]);
}

/** 1 − SS_res/SS_tot, mirroring calc/fit_quality.r_squared exactly
 *  (including its degenerate-SS_tot convention: a constant `actual`
 *  window has no variance to explain, so this returns 0 rather than
 *  NaN/±Infinity from a 0/0 division). */
export function rSquared(actual: number[], model: number[]): number {
  if (actual.length !== model.length) {
    throw new Error(
      `rSquared: actual (${actual.length}) and model (${model.length}) must be the same length`,
    );
  }
  const n = actual.length;
  if (n === 0) return 0;
  const mean = actual.reduce((sum, a) => sum + a, 0) / n;
  const ssTot = actual.reduce((sum, a) => sum + (a - mean) ** 2, 0);
  if (ssTot <= 0) return 0;
  const ssRes = actual.reduce((sum, a, i) => sum + (a - model[i]) ** 2, 0);
  return 1 - ssRes / ssTot;
}
