// Measure display-unit conversion (owner-approved design, plans/todo item
// "measure display units"): lets a per-measure preference override the
// unit a length/area label renders in, independent of the image's
// calibration unit. Pure, no component/store imports — mirrors the
// separation lib/geometry.ts and lib/regionTable.ts already keep.
//
// This module deliberately does NOT reuse lib/geometry.ts's `unitToNm`:
// that helper only serves the scale-bar's Å/nm/µm chain and has no `mm`
// step, while this feature's menu (owner spec) offers Å/nm/µm/mm. Both
// helpers agree on the nm-per-unit factors for the units they share.

/** A measure's display-unit preference. `"auto"` picks the largest unit
 *  whose displayed value is >= 0.01; the other four pin a fixed unit.
 *  Absent on the Measure itself (not part of this union) means "image
 *  default" — render the calibration unit verbatim, exactly as before
 *  this feature existed. */
export type DisplayUnit = "auto" | "A" | "nm" | "um" | "mm";

/** nm-per-unit for the fixed choices, in the SAME order the "largest
 *  unit whose value is >= 0.01" search walks (biggest first). Å is the
 *  mandatory fallback so it is not part of this ordered list — every
 *  Auto search ends there if nothing bigger qualifies. */
const FIXED_UNIT_TO_NM: Record<Exclude<DisplayUnit, "auto">, number> = {
  mm: 1e6,
  um: 1e3,
  nm: 1,
  A: 0.1,
};

/** Canonical display glyph for each fixed choice. */
const GLYPH: Record<Exclude<DisplayUnit, "auto">, string> = {
  mm: "mm",
  um: "µm",
  nm: "nm",
  A: "Å",
};

/** Auto's search order, largest unit first — Å is the unconditional
 *  fallback and is intentionally not in this list (see FIXED_UNIT_TO_NM
 *  doc above). */
const AUTO_ORDER: (Exclude<DisplayUnit, "auto" | "A">)[] = ["mm", "um", "nm"];

/** Below this displayed magnitude Auto steps down to a smaller unit —
 *  the owner-ratified boundary ("largest unit for which the displayed
 *  value is >= 0.01"). */
const AUTO_MIN_MAGNITUDE = 0.01;

/** Parse a calibration unit string as found in AxisCal.units (ImageMeta
 *  .pixel_unit) — accepts the spellings that occur in the wild ("nm",
 *  "µm"/"um", "Å"/"A"/"angstrom", "mm"), case-insensitively. Returns the
 *  factor to convert a value in `unit` to nm, or null when the string
 *  cannot be linearly converted at all: empty, "px" (uncalibrated),
 *  a reciprocal calibration such as "1/nm" (diffraction), or any other
 *  unrecognized spelling. Never guesses — an unrecognized string must
 *  never silently "convert". */
export function linearUnitToNm(unit: string): number | null {
  if (typeof unit !== "string") return null;
  const trimmed = unit.trim();
  if (trimmed === "") return null;
  // normalize both the "µ" (U+00B5 MICRO SIGN) and "μ" (U+03BC GREEK MU)
  // spellings some sources use for the same glyph, then fold case.
  const s = trimmed.replace(/μ/g, "µ").toLowerCase();
  switch (s) {
    case "å":
    case "a":
    case "ang":
    case "angstrom":
    case "ångström":
      return FIXED_UNIT_TO_NM.A;
    case "nm":
      return FIXED_UNIT_TO_NM.nm;
    case "µm":
    case "um":
      return FIXED_UNIT_TO_NM.um;
    case "mm":
      return FIXED_UNIT_TO_NM.mm;
    default:
      // covers "px", "1/nm" and anything else not explicitly listed above
      return null;
  }
}

/** Length in calibration units + the measure's choice -> {value, unit}
 *  for display (canonical glyphs "Å"/"nm"/"µm"/"mm"), or null meaning
 *  "no conversion possible — render as today" (uncalibrated, reciprocal
 *  or unrecognized calibration unit, or a non-finite `value`).
 *
 *  PR #159 critical-review fix 1 ("precision belongs to display sites,
 *  not the lib"): this used to round the result to 3 significant figures
 *  before returning it, which corrupted every consumer that needs more
 *  than a label's worth of precision — CSV export (measurePanelUtils.ts
 *  showLog) most visibly, but also identity conversions (850.4 nm + "nm"
 *  chosen explicitly used to come back as 850). The value returned here
 *  is now the FULL-precision conversion; each display site applies its
 *  own existing precision convention on top (the stage label and the
 *  MeasurePanel row both round to 3 sig figs — formatScaleLength's,
 *  lib/geometry.ts, convention — right where they format the string;
 *  showLog keeps its own 6-sig-fig format applied to the untouched
 *  value). */
export function displayLength(
  value: number,
  calUnit: string,
  choice: DisplayUnit,
): { value: number; unit: string } | null {
  // PR #159 critical-review fix 2: a non-finite `value` (NaN/Infinity —
  // a broken measurement) must never convert to a confident-looking
  // number. round3 used to fold NaN/Infinity to 0 as a side effect of
  // its own Number.isFinite guard; now that rounding has moved out of
  // this function entirely, the non-finite guard has to be explicit here
  // instead of arriving for free — null tells the caller "no conversion
  // possible", the same signal an unrecognized calibration unit gives,
  // which every caller already falls back on to render today's '—'/NaN
  // handling rather than inventing a value.
  if (!Number.isFinite(value)) return null;
  const calToNm = linearUnitToNm(calUnit);
  if (calToNm == null) return null;
  const nmValue = value * calToNm;

  if (choice === "auto") {
    // "value 0 renders in the calibration unit" (owner spec) — signal
    // the caller to fall back to its existing render, not a fabricated
    // "0 Å".
    if (value === 0) return null;
    for (const unit of AUTO_ORDER) {
      const v = nmValue / FIXED_UNIT_TO_NM[unit];
      if (Math.abs(v) >= AUTO_MIN_MAGNITUDE) return { value: v, unit: GLYPH[unit] };
    }
    return { value: nmValue / FIXED_UNIT_TO_NM.A, unit: GLYPH.A };
  }

  const outFactor = FIXED_UNIT_TO_NM[choice];
  return { value: nmValue / outFactor, unit: GLYPH[choice] };
}

/** Same as displayLength but for AREAS: `valueSq` is in calUnit² and the
 *  conversion factors are SQUARED (nm² -> µm² divides by 1e6, not 1e3) —
 *  the units trap this feature exists to get right. Output unit is like
 *  "µm²". Full-precision return + non-finite guard: see displayLength's
 *  doc above (PR #159 critical-review fixes 1 and 2 — identical
 *  reasoning, mirrored here for the squared-factor path). */
export function displayArea(
  valueSq: number,
  calUnit: string,
  choice: DisplayUnit,
): { value: number; unit: string } | null {
  if (!Number.isFinite(valueSq)) return null;
  const calToNm = linearUnitToNm(calUnit);
  if (calToNm == null) return null;
  const calToNmSq = calToNm * calToNm;
  const nmSqValue = valueSq * calToNmSq;

  if (choice === "auto") {
    if (valueSq === 0) return null;
    for (const unit of AUTO_ORDER) {
      const factorSq = FIXED_UNIT_TO_NM[unit] * FIXED_UNIT_TO_NM[unit];
      const v = nmSqValue / factorSq;
      if (Math.abs(v) >= AUTO_MIN_MAGNITUDE) {
        return { value: v, unit: `${GLYPH[unit]}²` };
      }
    }
    const aFactorSq = FIXED_UNIT_TO_NM.A * FIXED_UNIT_TO_NM.A;
    return { value: nmSqValue / aFactorSq, unit: `${GLYPH.A}²` };
  }

  const outFactorSq = FIXED_UNIT_TO_NM[choice] * FIXED_UNIT_TO_NM[choice];
  return { value: nmSqValue / outFactorSq, unit: `${GLYPH[choice]}²` };
}
