// What a box profile's line is doing in the image: its direction, and the
// perpendicular extent being averaged into every sample.
//
// Both are already true of the measurement — `calc.profiles.line_profile`
// samples along an arbitrary-angle segment, and `width` sets how many
// parallel offset lines are averaged — but neither reached the user. A
// profile that runs at 7 deg and one that runs at 0 deg look the same on a
// plot and mean different things: on a tilted layer stack the first is
// measuring across the stack and the second is measuring along it.

import type { Measure } from "../store/viewerTypes";

export interface ProfileGeometry {
  /** direction from the image's +x axis, degrees, in (-90, 90]. Horizontal
      is 0; the sign follows image coordinates, where +y runs DOWN. */
  angleDeg: number;
  /** perpendicular averaging extent, image pixels. 1 is a single-pixel
      line, not a box. */
  widthPx: number;
}

/**
 * `null` when the measure is not a two-point profile — a polyline has no
 * single direction, so reporting one would be a claim the data does not
 * support.
 */
export function profileGeometry(
  measure: Measure | undefined,
  img: { w: number; h: number },
): ProfileGeometry | null {
  if (!measure || measure.kind !== "profile" || measure.pts.length !== 2) {
    return null;
  }
  const [a, b] = measure.pts;
  // pts are normalised fractions; multiply back so a non-square image does
  // not report an angle that is only true in fraction space
  const dx = (b.x - a.x) * img.w;
  const dy = (b.y - a.y) * img.h;
  if (dx === 0 && dy === 0) return null;
  let angleDeg = (Math.atan2(dy, dx) * 180) / Math.PI;
  // A profile has no head and tail for this purpose: reversing the drag
  // direction must not flip the reported angle by 180 deg, so fold to
  // (-90, 90].
  if (angleDeg > 90) angleDeg -= 180;
  if (angleDeg <= -90) angleDeg += 180;
  return { angleDeg, widthPx: measure.width ?? 1 };
}
