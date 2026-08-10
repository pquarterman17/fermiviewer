// The MeasureKind partition, in ONE place.
//
// Why this module exists: "Clear Measurements" and "Clear Annotations" each
// act on one half of MeasureKind, and each carried its own inline literal
// list inside a menu-action closure. Adding "polygon" and "lasso" to the
// union compiled cleanly everywhere while silently leaving both kinds
// unclearable — a real bug (2026-08-09) that a green suite did not catch,
// because nothing anywhere related the two lists to the union they partition.
//
// Adding a member to a union is invisible to the type checker at any site
// that enumerates members by hand. The fix is to make the enumeration a
// single declared thing the compiler can check, which is what the
// exhaustiveness assertion at the bottom does.

import type { MeasureKind } from "../store/viewerTypes";

/** Kinds that measure something — the geometry tools. Cleared by
 *  Edit ▸ Clear Measurements. */
export const MEASUREMENT_KINDS = [
  "distance",
  "profile",
  "angle",
  "roi",
  "ellipse",
  "polyline",
  "polygon",
  "lasso",
] as const satisfies readonly MeasureKind[];

/** Kinds that annotate — they carry a caption, not a measured value.
 *  Cleared by Edit ▸ Clear Annotations. */
export const ANNOTATION_KINDS = [
  "text",
  "arrow",
  "box",
  "circle",
] as const satisfies readonly MeasureKind[];

/** Every kind, measurement then annotation. */
export const ALL_MEASURE_KINDS = [
  ...MEASUREMENT_KINDS,
  ...ANNOTATION_KINDS,
] as const satisfies readonly MeasureKind[];

// COMPILE-TIME exhaustiveness. Add a member to MeasureKind and forget to
// place it in exactly one list above, and `Unpartitioned` stops being
// `never`, so this assignment fails to type-check. That is the guard the
// inline literals could not provide: a build error at the moment of the
// mistake, instead of a feature that quietly does nothing to the new kind.
type Unpartitioned = Exclude<MeasureKind, (typeof ALL_MEASURE_KINDS)[number]>;
const _everyKindIsPartitioned: Unpartitioned extends never
  ? true
  : Unpartitioned = true;
void _everyKindIsPartitioned;

/** True when `kind` measures something rather than annotating. */
export function isMeasurementKind(kind: MeasureKind): boolean {
  return (MEASUREMENT_KINDS as readonly MeasureKind[]).includes(kind);
}
