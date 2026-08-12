// EDS detector energy resolution — the Fiori–Newbury FWHM(E) curve.
//
// A deliberate client-side port of `calc/eds_calib.py::fano_fwhm`, for the
// same reason `lib/eels/integrate.ts` ports the EELS background: window
// editing has to answer "how wide should this window be?" without a round
// trip, and a preset click that can fail offline is worse than one that
// cannot. It is a closed-form expression over three constants, so the port
// is the whole formula rather than a summary of it.
//
// KEPT IN LOCKSTEP the only way two languages can be: `resolution.test.ts`
// and `tests/test_eds_calib.py` pin the SAME sample values (0.277 / 1.0 /
// 5.899 / 8.048 / 15.0 keV). Change a constant on either side and one of the
// two suites goes red. Do not "fix" one file's numbers to match the other
// without changing both.

/** Mean energy per electron-hole pair in Si, eV. */
export const EPSILON_EV = 3.85;
/** Fano factor for Si. */
export const FANO = 0.12;
/** Reference line anchoring the electronic-noise term: Mn-Kα. */
export const MN_KA_KEV = 5.899;
/** Typical SDD spec resolution at Mn-Kα, eV. */
export const MN_KA_FWHM_EV = 130.0;

/** 2·√(2·ln2) — the FWHM ↔ Gaussian-σ conversion factor. */
export const FWHM_PER_SIGMA = 2 * Math.sqrt(2 * Math.LN2);

/**
 * Detector resolution FWHM in **eV** at `energyKev`.
 *
 * `FWHM(E)² = FWHM_noise² + (2·√(2·ln2))²·F·ε·E`, with the noise term
 * back-solved so the curve passes exactly through the Mn-Kα anchor. The
 * variance is clamped at 0 so an energy far below the anchor returns a small
 * real width instead of NaN — the same clamp the Python side applies.
 */
export function fanoFwhmEv(energyKev: number): number {
  const slope = FWHM_PER_SIGMA ** 2 * FANO * EPSILON_EV; // eV² per eV
  const noiseSq = MN_KA_FWHM_EV ** 2 - slope * MN_KA_KEV * 1000;
  return Math.sqrt(Math.max(noiseSq + slope * energyKev * 1000, 0));
}

/** The same width in keV, which is the unit EDS windows are expressed in. */
export function fanoFwhmKev(energyKev: number): number {
  return fanoFwhmEv(energyKev) / 1000;
}
