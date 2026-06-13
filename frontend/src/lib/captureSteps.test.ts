// CAPTURE_STEPS (GUI v2 capture banner): step copy must exist for every
// banner mode and the click-mode step counts must mirror Stage's CLICKS.

import { describe, expect, it } from "vitest";

import { CAPTURE_STEPS } from "./captureSteps";
import type { CaptureMode } from "../store/viewer";

const BANNER_MODES: CaptureMode[] = [
  "zoom",
  "box-profile",
  "distance",
  "profile",
  "angle",
  "roi",
  "ellipse",
  "polyline",
  "text",
  "arrow",
  "box",
  "circle",
];

describe("CAPTURE_STEPS", () => {
  it("every banner mode has a non-empty label and steps", () => {
    for (const mode of BANNER_MODES) {
      const entry = CAPTURE_STEPS[mode];
      expect(entry, mode).toBeDefined();
      expect(entry!.label.length).toBeGreaterThan(0);
      expect(entry!.steps.length).toBeGreaterThan(0);
      for (const step of entry!.steps) expect(step.length).toBeGreaterThan(0);
    }
  });

  it("click modes have one step per click (matches CLICKS)", () => {
    const counts: Record<string, number> = {
      distance: 2,
      profile: 2,
      angle: 3,
      text: 1,
      arrow: 2,
      box: 2,
      circle: 2,
    };
    for (const [mode, n] of Object.entries(counts)) {
      expect(CAPTURE_STEPS[mode as CaptureMode]!.steps.length, mode).toBe(n);
    }
  });

  it("drag + polyline modes are single-step", () => {
    const single: CaptureMode[] = [
      "roi",
      "ellipse",
      "box-profile",
      "zoom",
      "polyline",
    ];
    for (const mode of single) {
      expect(CAPTURE_STEPS[mode]!.steps.length, mode).toBe(1);
    }
  });

  it("none and fixed-zoom have no banner entry", () => {
    expect(CAPTURE_STEPS["none"]).toBeUndefined();
    expect(CAPTURE_STEPS["fixed-zoom"]).toBeUndefined();
  });
});
