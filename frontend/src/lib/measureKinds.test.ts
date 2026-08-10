// Guards for the MeasureKind partition. The bug these exist for: both
// "Clear Measurements" and "Clear Annotations" carried inline kind lists, so
// adding "polygon"/"lasso" to the union compiled fine and left both kinds
// unclearable. The compile-time assertion in measureKinds.ts is the primary
// guard; these cover the properties a type cannot express.

import { describe, expect, it } from "vitest";

import {
  ALL_MEASURE_KINDS,
  ANNOTATION_KINDS,
  MEASUREMENT_KINDS,
  isMeasurementKind,
} from "./measureKinds";

describe("MeasureKind partition", () => {
  it("is disjoint — no kind is both a measurement and an annotation", () => {
    const overlap = MEASUREMENT_KINDS.filter((k) =>
      (ANNOTATION_KINDS as readonly string[]).includes(k),
    );
    expect(overlap).toEqual([]);
  });

  it("has no duplicates within or across the halves", () => {
    expect(new Set(ALL_MEASURE_KINDS).size).toBe(ALL_MEASURE_KINDS.length);
  });

  it("accounts for every kind exactly once", () => {
    // Completeness against the union itself is enforced at COMPILE time by
    // measureKinds.ts's Unpartitioned assertion — a runtime test cannot
    // enumerate a TypeScript union. What this pins is the arithmetic: the
    // two halves sum to the whole, so a kind cannot be dropped from one
    // list and quietly absorbed by the other.
    expect(ALL_MEASURE_KINDS.length).toBe(
      MEASUREMENT_KINDS.length + ANNOTATION_KINDS.length,
    );
  });

  it("classifies each half correctly", () => {
    expect(MEASUREMENT_KINDS.every(isMeasurementKind)).toBe(true);
    expect(ANNOTATION_KINDS.some(isMeasurementKind)).toBe(false);
  });

  it("puts the area kinds on the measurement side", () => {
    // The specific regression: these two were in neither list, so neither
    // menu item touched them.
    expect(isMeasurementKind("polygon")).toBe(true);
    expect(isMeasurementKind("lasso")).toBe(true);
  });
});
