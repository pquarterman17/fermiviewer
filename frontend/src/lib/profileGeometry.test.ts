import { describe, expect, it } from "vitest";

import type { Measure } from "../store/viewerTypes";
import { profileGeometry } from "./profileGeometry";

const SQUARE = { w: 100, h: 100 };

const profile = (
  pts: { x: number; y: number }[],
  width?: number,
): Measure => ({ id: "m", kind: "profile", pts, width }) as unknown as Measure;

describe("profileGeometry", () => {
  it("reports 0 for a horizontal profile and 90 for a vertical one", () => {
    const flat = profileGeometry(
      profile([{ x: 0.1, y: 0.5 }, { x: 0.9, y: 0.5 }]),
      SQUARE,
    );
    expect(flat?.angleDeg).toBeCloseTo(0, 9);
    const up = profileGeometry(
      profile([{ x: 0.5, y: 0.1 }, { x: 0.5, y: 0.9 }]),
      SQUARE,
    );
    expect(up?.angleDeg).toBeCloseTo(90, 9);
  });

  it("does not flip when the same line is drawn the other way round", () => {
    const a = profileGeometry(
      profile([{ x: 0.2, y: 0.2 }, { x: 0.8, y: 0.5 }]),
      SQUARE,
    );
    const b = profileGeometry(
      profile([{ x: 0.8, y: 0.5 }, { x: 0.2, y: 0.2 }]),
      SQUARE,
    );
    // a profile has no head and tail for this purpose; reporting 26.6 one
    // way and -153.4 the other would read as two different measurements
    expect(a?.angleDeg).toBeCloseTo(b!.angleDeg, 9);
  });

  it("measures the angle in image pixels, not in fraction space", () => {
    // the same normalised endpoints on a 2:1 image are NOT the same
    // direction: a naive atan2 on fractions would report 45° for both
    const wide = profileGeometry(
      profile([{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }]),
      { w: 200, h: 100 },
    );
    expect(wide?.angleDeg).toBeCloseTo(
      (Math.atan2(50, 100) * 180) / Math.PI,
      9,
    );
    expect(wide?.angleDeg).not.toBeCloseTo(45, 1);
  });

  it("reports no direction for a polyline, which has more than one", () => {
    const poly = profile([
      { x: 0.1, y: 0.1 },
      { x: 0.5, y: 0.5 },
      { x: 0.9, y: 0.2 },
    ]);
    expect(profileGeometry(poly, SQUARE)).toBeNull();
  });

  it("reports no direction for a zero-length line, and none for no measure", () => {
    expect(
      profileGeometry(profile([{ x: 0.5, y: 0.5 }, { x: 0.5, y: 0.5 }]), SQUARE),
    ).toBeNull();
    expect(profileGeometry(undefined, SQUARE)).toBeNull();
  });

  it("defaults an unset width to a single pixel, not a box", () => {
    expect(
      profileGeometry(profile([{ x: 0, y: 0.5 }, { x: 1, y: 0.5 }]), SQUARE)
        ?.widthPx,
    ).toBe(1);
    expect(
      profileGeometry(profile([{ x: 0, y: 0.5 }, { x: 1, y: 0.5 }], 24), SQUARE)
        ?.widthPx,
    ).toBe(24);
  });
});
