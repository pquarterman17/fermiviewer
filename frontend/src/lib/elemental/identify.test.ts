import { describe, expect, it } from "vitest";

import type { EdsAutoAssignResult, Spectrum } from "../api";
import { confidenceOf, identifyElements, measureElement } from "./identify";

// A spectrum with a towering peak at 5 keV, a modest one at 3 keV and a
// barely-there bump at 8 keV, all on a flat background.
function spectrum(): Spectrum {
  const energy: number[] = [];
  const counts: number[] = [];
  for (let i = 0; i < 200; i++) {
    const e = i * 0.05;
    energy.push(e);
    let c = 100;
    if (Math.abs(e - 5.0) < 0.03) c += 400_000;
    if (Math.abs(e - 3.0) < 0.03) c += 20_000;
    if (Math.abs(e - 8.0) < 0.03) c += 60;
    counts.push(c);
  }
  return { energy, counts, units: "keV" };
}

function auto(
  pairs: [number, string, string, number][],
): EdsAutoAssignResult {
  return {
    peaks_kev: pairs.map(([p]) => p),
    assignments: pairs.map(([peak, symbol, line, energy]) => ({
      peak_kev: peak,
      candidates: [
        { symbol, line, energy_kev: energy, delta_kev: peak - energy },
      ],
    })),
  };
}

describe("confidenceOf", () => {
  it("bands by significance, not by peak height", () => {
    expect(confidenceOf(500)).toBe("strong");
    expect(confidenceOf(100)).toBe("strong");
    expect(confidenceOf(45)).toBe("clear");
    expect(confidenceOf(12)).toBe("weak");
    expect(confidenceOf(3)).toBe("trace");
    expect(confidenceOf(-5)).toBe("trace");
  });
});

describe("identifyElements", () => {
  const result = identifyElements(
    auto([
      [5.0, "Fe", "K", 5.0],
      [3.0, "Ca", "K", 3.0],
      [8.0, "Cu", "K", 8.0],
    ]),
    spectrum(),
  );

  it("returns one row per element, strongest first", () => {
    expect(result.map((r) => r.symbol)).toEqual(["Fe", "Ca", "Cu"]);
  });

  it("measures net counts from the spectrum rather than trusting the match", () => {
    const fe = result[0];
    expect(fe.net).toBeGreaterThan(300_000);
    expect(fe.significance).toBeGreaterThan(100);
    expect(fe.confidence).toBe("strong");
  });

  it("leaves a trace-level match unticked but present", () => {
    const cu = result.find((r) => r.symbol === "Cu")!;
    expect(cu.confidence).toBe("trace");
    expect(cu.recommended).toBe(false);
    // still in the list — a real trace element must remain reachable
    expect(result).toHaveLength(3);
  });

  it("scales the strength bar against the strongest element", () => {
    expect(result[0].relative).toBe(1);
    expect(result[1].relative).toBeLessThan(1);
    expect(result[1].relative).toBeGreaterThan(0);
  });

  it("collapses an element matched by several peaks to its best match", () => {
    const merged = identifyElements(
      auto([
        [5.0, "Fe", "K", 5.0],
        [5.02, "Fe", "K", 5.0],
        [4.9, "Fe", "L", 5.0],
      ]),
      spectrum(),
    );
    expect(merged).toHaveLength(1);
    expect(merged[0].deltaKev).toBeCloseTo(0, 10);
  });

  it("returns nothing without a spectrum to measure against", () => {
    expect(identifyElements(auto([[5, "Fe", "K", 5]]), null)).toEqual([]);
    expect(identifyElements(null, spectrum())).toEqual([]);
  });
});

describe("measureElement", () => {
  it("measures a manually added element the same way, and ticks it", () => {
    const spec = spectrum();
    const existing = identifyElements(auto([[5.0, "Fe", "K", 5.0]]), spec);
    const added = measureElement("Ca", "K", 3.0, spec, existing)!;
    expect(added.symbol).toBe("Ca");
    expect(added.net).toBeGreaterThan(10_000);
    // an element the user asked for is shown even if it reads as trace
    expect(added.recommended).toBe(true);
    expect(added.relative).toBeLessThan(1);
  });
});
