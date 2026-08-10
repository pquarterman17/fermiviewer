// stageScaleLock.ts — the two Stage.tsx call sites for the
// constant-physical-scale lock (plan item 8). The underlying math
// (resolveScaleView/physicalScale/fitView) is covered by
// lib/geometry.test.ts; these tests exercise the exact call shape
// Stage.tsx uses, so a regression here means Stage itself would jump.

import { describe, expect, it, vi } from "vitest";

import { fitView, physicalScale } from "../../lib/geometry";
import {
  defaultStageView,
  fitAndReseedScale,
  runFitAndReseed,
} from "./stageScaleLock";

const vp = { w: 400, h: 300 };

describe("defaultStageView", () => {
  it("no image → null", () => {
    expect(defaultStageView(null, null, vp, 2, { locked: true, scale: 1 }))
      .toBeNull();
  });

  it("a stored view always wins, even while locked — enabling the lock (or a locked series) never jumps the CURRENT image", () => {
    const stored = { z: 3, px: 0.2, py: 0.8 };
    const got = defaultStageView(stored, { w: 512, h: 512 }, vp, 2, {
      locked: true,
      scale: 999,
    });
    expect(got).toBe(stored);
  });

  it("locked + calibrated, two images with DIFFERENT pixel sizes and no stored view: holds one physical scale across the switch, so a feature keeps its on-screen size", () => {
    const target = 0.5; // pixel_unit per screen px, shared across the series
    const imgA = { w: 512, h: 512 };
    const pixelSizeA = 2; // pixel_unit per image px
    const imgB = { w: 800, h: 600 }; // deliberately a different pixel size
    const pixelSizeB = 5;
    const lock = { locked: true, scale: target };

    const viewA = defaultStageView(null, imgA, vp, pixelSizeA, lock)!;
    const viewB = defaultStageView(null, imgB, vp, pixelSizeB, lock)!;

    expect(physicalScale(viewA, pixelSizeA)).toBeCloseTo(target, 10);
    expect(physicalScale(viewB, pixelSizeB)).toBeCloseTo(target, 10);

    // a 100-unit feature must occupy the same screen width in both frames
    const featureUnits = 100;
    const screenWidthA = (featureUnits / pixelSizeA) * viewA.z;
    const screenWidthB = (featureUnits / pixelSizeB) * viewB.z;
    expect(screenWidthA).toBeCloseTo(screenWidthB, 10);

    // differing image dimensions still letterbox differently — the lock
    // fixes scale, not pan/centre framing, and that's accepted by design
    expect(viewA.z).not.toBeCloseTo(viewB.z, 5);
  });

  it("lock off → fitView, unchanged from the pre-lock default", () => {
    const img = { w: 512, h: 512 };
    const got = defaultStageView(null, img, vp, 2, {
      locked: false,
      scale: 7,
    });
    expect(got).toEqual(fitView(img, vp));
  });

  it("uncalibrated image (pixel_size null) → fitView even while locked", () => {
    const img = { w: 512, h: 512 };
    const got = defaultStageView(null, img, vp, null, {
      locked: true,
      scale: 1,
    });
    expect(got).toEqual(fitView(img, vp));
  });

  it("locked but not yet seeded (scale null) → fitView", () => {
    const img = { w: 512, h: 512 };
    const got = defaultStageView(null, img, vp, 2, {
      locked: true,
      scale: null,
    });
    expect(got).toEqual(fitView(img, vp));
  });
});

describe("fitAndReseedScale", () => {
  it("always returns the plain fitView, regardless of the lock", () => {
    const img = { w: 640, h: 480 };
    expect(fitAndReseedScale(img, vp, 2, true).view).toEqual(fitView(img, vp));
    expect(fitAndReseedScale(img, vp, null, false).view).toEqual(
      fitView(img, vp),
    );
  });

  it("locked + calibrated: reseeds to the fitted view's own physical scale, so the NEXT image matches what was just fitted", () => {
    const img = { w: 640, h: 480 };
    const pixelSize = 3;
    const { view, reseedTo } = fitAndReseedScale(img, vp, pixelSize, true);
    expect(reseedTo).toBeCloseTo(physicalScale(view, pixelSize), 10);
  });

  it("locked but uncalibrated → does not reseed (null)", () => {
    const img = { w: 640, h: 480 };
    for (const pixelSize of [null, 0, NaN, Infinity, -1]) {
      expect(fitAndReseedScale(img, vp, pixelSize, true).reseedTo).toBeNull();
    }
  });

  it("not locked → never reseeds, even when calibrated", () => {
    const img = { w: 640, h: 480 };
    expect(fitAndReseedScale(img, vp, 3, false).reseedTo).toBeNull();
  });
});

// #9's carried-over defect: double-click-to-fit on CompareStage.tsx,
// SideBySideStage.tsx and useStagePointers.ts must re-seed the browse-scale
// lock exactly like Stage.tsx's imperative fit() does. runFitAndReseed is
// the one place all three now share that sequencing.
describe("runFitAndReseed (double-click-to-fit re-seeds the lock — item 9)", () => {
  it("always applies the fitted view", () => {
    const img = { w: 640, h: 480 };
    const applyView = vi.fn();
    const reseedScale = vi.fn();
    runFitAndReseed(img, vp, 2, true, applyView, reseedScale);
    expect(applyView).toHaveBeenCalledWith(fitView(img, vp));
  });

  it("locked + calibrated: reseeds to the fitted view's own physical scale", () => {
    const img = { w: 640, h: 480 };
    const pixelSize = 3;
    const applyView = vi.fn();
    const reseedScale = vi.fn();
    runFitAndReseed(img, vp, pixelSize, true, applyView, reseedScale);
    const [fitted] = applyView.mock.calls[0] as [ReturnType<typeof fitView>];
    expect(reseedScale).toHaveBeenCalledWith(physicalScale(fitted, pixelSize));
  });

  it("unlocked or uncalibrated: applies the view but never reseeds", () => {
    const img = { w: 640, h: 480 };
    const applyView = vi.fn();
    const reseedScale = vi.fn();
    runFitAndReseed(img, vp, 3, false, applyView, reseedScale);
    expect(applyView).toHaveBeenCalled();
    expect(reseedScale).not.toHaveBeenCalled();

    runFitAndReseed(img, vp, null, true, applyView, reseedScale);
    expect(reseedScale).not.toHaveBeenCalled();
  });
});
