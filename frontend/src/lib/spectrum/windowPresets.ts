// Window WIDTH presets, for either modality (SPECTRAL_WORKSPACE_PLAN #5).
//
// Width is the control that actually changes an answer: too narrow and the
// map is noise-limited, too wide and it collects the neighbouring line. The
// two modalities set it from genuinely different physics, which is why this
// module dispatches on modality rather than offering one set of numbers:
//
//   EDS  — the window brackets a Gaussian peak, so the meaningful unit is the
//          DETECTOR resolution at that line (Fiori–Newbury FWHM, ported in
//          lib/eds/resolution.ts). A fixed ±85 eV is 1.3 FWHM at C-Kα and
//          0.65 FWHM at Mn-Kα: the same number means two different things.
//   EELS — the edge is a step, not a peak; there is nothing to bracket. The
//          real control is how far PAST the onset to integrate, and the
//          conventional widths are absolute (Egerton), not resolution-scaled.
//
// `fitPeakWindow` is the "refine on the data" half: presets say what the
// detector should give you, the fit says what this spectrum actually has.

import { fanoFwhmKev } from "../eds/resolution";
import {
  EELS_SIGNAL_WIDTH_EV,
  edsDefaultWindows,
  eelsDefaultWindows,
  type Modality,
  type SpeciesWindows,
} from "./species";

export type WindowPreset = "narrow" | "standard" | "wide";

export const WINDOW_PRESETS: readonly WindowPreset[] = [
  "narrow",
  "standard",
  "wide",
] as const;

/**
 * EDS window width as a multiple of the detector FWHM at the line.
 *
 * Quoted as TOTAL width, which is how EDS software states an ROI. For a
 * Gaussian peak these capture 76 % / 92 % / 98 % of its area; the fraction is
 * constant across elements, so a ratio-based quantification is unaffected by
 * which one is chosen — the trade is purely counting statistics against
 * overlap with the neighbouring line.
 */
export const EDS_PRESET_FWHM_MULTIPLE: Record<WindowPreset, number> = {
  narrow: 1.0,
  standard: 1.5,
  wide: 2.0,
};

/**
 * EELS integration width past the onset, eV.
 *
 * `standard` is `EELS_SIGNAL_WIDTH_EV` itself, not a copy of its value, so
 * the preset row and the default a fresh species is born with cannot drift —
 * and both stay in the lockstep that constant already keeps with
 * `calc/eels_identify.py`.
 */
export const EELS_PRESET_WIDTH_EV: Record<WindowPreset, number> = {
  narrow: 30,
  standard: EELS_SIGNAL_WIDTH_EV,
  wide: 100,
};

/** The width a preset produces, in the modality's own unit — for a tooltip
 *  that says what the button will do before it is pressed. */
export function presetWidth(
  modality: Modality,
  anchorEnergy: number,
  preset: WindowPreset,
): number {
  return modality === "eds"
    ? fanoFwhmKev(anchorEnergy) * EDS_PRESET_FWHM_MULTIPLE[preset]
    : EELS_PRESET_WIDTH_EV[preset];
}

/**
 * Windows for `preset`, anchored to `anchorEnergy` — the tabulated line (EDS,
 * keV) or the edge onset (EELS, eV).
 *
 * EDS centres the window on the line; EELS starts it AT the onset and runs
 * upward, re-placing the pre-edge background window below it. Both delegate
 * to the same `*DefaultWindows` builders a fresh species uses, so a preset
 * and a default differ only in width.
 */
export function presetWindows(
  modality: Modality,
  anchorEnergy: number,
  preset: WindowPreset,
): SpeciesWindows {
  if (modality === "eds") {
    return edsDefaultWindows(anchorEnergy, presetWidth("eds", anchorEnergy, preset) / 2);
  }
  return eelsDefaultWindows(anchorEnergy, EELS_PRESET_WIDTH_EV[preset]);
}

/** Which preset a window's current width matches, or null when it is between
 *  presets (a hand-tuned window must not light up a button it did not set).
 *  `tolerance` is relative, so it means the same thing in keV and in eV. */
export function activePreset(
  modality: Modality,
  anchorEnergy: number,
  widthNow: number,
  tolerance = 1e-3,
): WindowPreset | null {
  for (const preset of WINDOW_PRESETS) {
    const want = presetWidth(modality, anchorEnergy, preset);
    if (want > 0 && Math.abs(widthNow - want) <= tolerance * want) return preset;
  }
  return null;
}

/** Minimum peak height above its local baseline, as a fraction of the peak's
 *  own counts, for `measurePeakFwhm` to trust the width it measures. */
const MIN_PEAK_CONTRAST = 0.05;

export interface PeakFit {
  /** Interpolated half-maximum crossings, in the spectrum's energy unit. */
  fwhm: number;
  /** Midpoint of the two crossings — the measured line position, which is
   *  NOT the tabulated one when the axis calibration has drifted. */
  center: number;
}

/**
 * Measure a peak's FWHM in `counts` near `aroundEnergy`.
 *
 * The half-maximum is taken above a straight baseline joining the two ends of
 * the search span, so a peak sitting on the bremsstrahlung continuum is not
 * measured from zero (which would inflate the width toward the search limit).
 * Returns null — never a guess — when the search span has no interior
 * maximum, or when either half-maximum crossing runs off the end of the span:
 * both mean the span is centred on something that is not a resolved peak, and
 * a made-up width would silently resize the user's window.
 */
export function measurePeakFwhm(
  energy: readonly number[],
  counts: readonly number[],
  aroundEnergy: number,
  searchHalfWidth: number,
): PeakFit | null {
  const n = Math.min(energy.length, counts.length);
  if (n < 3 || !(searchHalfWidth > 0)) return null;

  let lo = -1;
  let hi = -1;
  for (let i = 0; i < n; i++) {
    const inside =
      energy[i] >= aroundEnergy - searchHalfWidth &&
      energy[i] <= aroundEnergy + searchHalfWidth;
    if (inside) {
      if (lo < 0) lo = i;
      hi = i;
    }
  }
  if (lo < 0 || hi - lo < 2) return null;

  let peak = lo;
  for (let i = lo; i <= hi; i++) if (counts[i] > counts[peak]) peak = i;
  // A maximum ON the edge of the span is a shoulder of something outside it.
  if (peak === lo || peak === hi) return null;

  const baseAt = (i: number): number => {
    const t = (energy[i] - energy[lo]) / (energy[hi] - energy[lo] || 1);
    return counts[lo] + t * (counts[hi] - counts[lo]);
  };
  const height = counts[peak] - baseAt(peak);
  // The baseline is only a baseline if the trace actually comes down to it
  // inside the span. A peak far broader than the span never does: its two ends
  // sit high on the peak's own flanks, the "height above baseline" collapses to
  // a few counts, and the half-maximum crossings land absurdly close to the
  // apex — a measured FWHM an order of magnitude too NARROW, which would then
  // silently shrink the user's window. Requiring the peak to stand at least
  // 5 % of its own counts above the baseline rejects that case; it also
  // rejects a peak too weak for a width measurement to mean anything, where
  // leaving the window untouched is the right answer anyway.
  if (!(height > 0) || height < MIN_PEAK_CONTRAST * counts[peak]) return null;
  const half = baseAt(peak) + height / 2;

  /** Energy where the trace crosses `half` walking `step` from the peak. */
  const crossing = (step: -1 | 1): number | null => {
    for (let i = peak; i >= lo && i <= hi; i += step) {
      const above = counts[i] - half;
      if (above <= 0) {
        const prev = i - step;
        const gap = counts[prev] - counts[i];
        if (gap === 0) return energy[i];
        const t = (counts[prev] - half) / gap;
        return energy[prev] + t * (energy[i] - energy[prev]);
      }
    }
    return null;
  };

  const left = crossing(-1);
  const right = crossing(1);
  if (left == null || right == null) return null;
  const fwhm = right - left;
  if (!(fwhm > 0)) return null;
  return { fwhm, center: (left + right) / 2 };
}

/**
 * EDS "fit the window to the measured peak": locate the peak near
 * `anchorKev`, measure its width, and return the window `preset` would ask
 * for at THAT width — so Fit and the preset buttons stay one control rather
 * than two competing ones. Null when there is no peak to fit, leaving the
 * user's window untouched.
 *
 * The search span is 3 × the modelled FWHM: wide enough that a mis-calibrated
 * axis still finds the peak, narrow enough that it cannot wander onto the
 * neighbouring line.
 */
export function fitPeakWindow(
  energy: readonly number[],
  counts: readonly number[],
  anchorKev: number,
  preset: WindowPreset = "standard",
): { windows: SpeciesWindows; fit: PeakFit } | null {
  const fit = measurePeakFwhm(energy, counts, anchorKev, 3 * fanoFwhmKev(anchorKev));
  if (!fit) return null;
  const half = (fit.fwhm * EDS_PRESET_FWHM_MULTIPLE[preset]) / 2;
  return { windows: edsDefaultWindows(fit.center, half), fit };
}
