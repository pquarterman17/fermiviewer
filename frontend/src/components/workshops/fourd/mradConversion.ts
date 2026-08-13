// Pixel <-> calibrated-unit conversion for the aperture radii, when the
// dataset's diffraction-plane calibration allows it (PLAN_4DSTEM #14). Pure
// and tiny by design: `value = px * scale` is trivial, but a mixed-up axis
// or a silently-fabricated unit here would mislabel every radius on screen,
// so the arithmetic is separated out and unit-tested on its own.
//
// A virtual-detector aperture radius is a single scalar with no axis of its
// own (routes/fourd.py's aperture_mask takes one `outer_r` in detector
// PIXELS, isotropic), so this needs ONE scale, not two. `detCalibration`
// only returns one when BOTH detector axes are calibrated AND agree on the
// unit — real 4D-STEM detectors are square-pixel and calibrated
// isotropically (see io/fourd/hspy4d.py's real-corpus tests), so this never
// excludes a genuinely calibrated file; it only refuses to silently pick
// one axis of a mismatched pair. Never fabricates a unit: an uncalibrated
// dataset (bare .mib, no .hdr sidecar) gets `null` and the px-only UI stays
// unchanged, matching the repo's "never a fake unit" rule.

import { isAxisCalibrated, type AxisCalOut } from "../../../lib/api";

export interface RadiusCalibration {
  /** Calibrated units per detector pixel. */
  scale: number;
  /** e.g. "mrad" — whatever the file's axis calibration says. */
  units: string;
}

/** The calibration to use for an aperture radius, or null when the
 *  detector isn't (fully, consistently) calibrated. */
export function detCalibration(
  detAxes: readonly AxisCalOut[] | undefined | null,
): RadiusCalibration | null {
  if (!detAxes || detAxes.length < 2) return null;
  const [ky, kx] = detAxes;
  if (!ky || !kx) return null;
  if (!isAxisCalibrated(ky) || !isAxisCalibrated(kx)) return null;
  if (ky.units !== kx.units) return null;
  return { scale: ky.scale, units: ky.units };
}

/** px -> calibrated units. */
export function pxToCalibrated(px: number, scale: number): number {
  return px * scale;
}

/** calibrated units -> px (the inverse of `pxToCalibrated`). */
export function calibratedToPx(value: number, scale: number): number {
  return value / scale;
}

/** Round-trip-stable display value: strips float noise (e.g.
 *  `12.5 * 0.1 / 0.1` landing a bit off 12.5) to a fixed sig-fig count so a
 *  typed value redisplays as exactly what was typed instead of visibly
 *  drifting under the user's cursor. */
export function roundForDisplay(value: number): number {
  return Number.isFinite(value) ? Number(value.toPrecision(6)) : value;
}

/** "≈ 12.3 mrad" secondary readout for a px radius, or null when
 *  uncalibrated / non-finite. */
export function formatCalibratedRadius(
  px: number,
  cal: RadiusCalibration | null,
): string | null {
  if (!cal || !Number.isFinite(px)) return null;
  return `≈ ${pxToCalibrated(px, cal.scale).toPrecision(3)} ${cal.units}`;
}
