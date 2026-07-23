import { describe, expect, it } from "vitest";

import type { EdsAutoAssignResult } from "../api";
import { buildPeakMarkers } from "./peakMarkers";

const auto = (
  assignments: EdsAutoAssignResult["assignments"],
): EdsAutoAssignResult => ({ peaks_kev: [], assignments });

describe("buildPeakMarkers", () => {
  it("merges selected lines and auto peaks, sorted by energy", () => {
    const markers = buildPeakMarkers(
      [{ symbol: "Si", line: "K", energy_kev: 1.74 }],
      auto([
        {
          peak_kev: 6.4,
          candidates: [
            { symbol: "Fe", line: "K", energy_kev: 6.404, delta_kev: 0.004 },
          ],
        },
      ]),
    );
    expect(markers.map((m) => m.label)).toEqual(["Si Kα", "Fe Kα"]);
    expect(markers[0].kind).toBe("selected");
    expect(markers[1].kind).toBe("auto");
  });

  it("lets a selected line win over an auto detection of the same line", () => {
    const markers = buildPeakMarkers(
      [{ symbol: "Fe", line: "K", energy_kev: 6.404 }],
      auto([
        {
          peak_kev: 6.4,
          candidates: [
            { symbol: "Fe", line: "K", energy_kev: 6.404, delta_kev: 0.004 },
          ],
        },
      ]),
    );
    expect(markers).toHaveLength(1);
    expect(markers[0].kind).toBe("selected");
  });

  it("returns nothing without data, and skips peaks with no candidate", () => {
    expect(buildPeakMarkers([], null)).toEqual([]);
    expect(
      buildPeakMarkers([], auto([{ peak_kev: 3.2, candidates: [] }])),
    ).toEqual([]);
  });
});
