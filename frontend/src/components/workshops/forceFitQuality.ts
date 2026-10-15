import type { ForceAnalysis } from "../../lib/api";

export type FitQuality = "Excellent" | "Good" | "Review" | "Poor" | "Not fitted";

export function forceFitQuality(result: ForceAnalysis): FitQuality {
  const r2 = result.values.fit_r2;
  const points = result.values.fit_points;
  if (r2 === null || points === null || points < 5) return "Not fitted";
  if (!result.evidence.calibration_complete || result.evidence.fit_at_bounds || r2 < 0.9 || points < 8) return "Poor";
  const structured = Math.abs(result.evidence.residual_lag1 ?? 0);
  if (r2 < 0.95 || points < 15 || structured > 0.5) return "Review";
  if (r2 < 0.98 || structured > 0.3) return "Good";
  return "Excellent";
}

export function forceWarnings(result: ForceAnalysis): string[] {
  const warnings: string[] = [];
  const { fit_r2: r2, fit_points: points, contact_slope: slope,
    noise_nm: noise, max_force: maxForce } = result.values;
  if (r2 !== null && r2 < 0.9) warnings.push("The contact model explains less than 90% of the fitted force variation.");
  if (points !== null && points > 0 && points < 10) warnings.push("The modulus fit uses fewer than 10 points; widen the fit range if appropriate.");
  if (slope !== null && Math.abs(slope - 1) > 0.15) warnings.push("Contact slope differs substantially from 1; verify InvOLS before trusting modulus.");
  if (noise !== null && maxForce !== null && maxForce > 0 && noise * result.spring_constant > 0.1 * maxForce) warnings.push("Baseline force noise exceeds 10% of the maximum force.");
  if (!result.evidence.calibration_complete) warnings.push("Calibration is incomplete; provide spring constant and InvOLS before interpreting modulus.");
  if (result.evidence.fit_at_bounds) warnings.push("A fitted parameter reached its allowed bound; adjust the fit window or verify the contact model.");
  if (Math.abs(result.evidence.residual_lag1 ?? 0) > 0.5) warnings.push("Residuals remain strongly structured; the contact model or fit window may not describe this curve.");
  return warnings;
}
