import { describe, expect, it } from "vitest";

import type { LayersResult } from "./api";
import { profileCsvText } from "./layersCsv";

const base = {
  axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.9,
  applied_tilt_deg: null, sampled_fraction: 1,
  depth_pos: [0, 1, 2], depth_profile: [10, 20, 30],
  interfaces: [], layers: [],
} as unknown as LayersResult;

describe("profileCsvText", () => {
  it("labels the pixel column as pixels, not as the calibrated unit", () => {
    // depth_pos is a plain index range from the backend. Calling that
    // column depth_nm made the export read as nanometres while holding
    // pixels — wrong by the pixel size, and invisible to the reader.
    const csv = profileCsvText({ ...base, pixel_size: 0.5, unit: "nm" });
    const [header, first] = csv.split("\n");
    expect(header).toBe("depth_px,depth_nm,intensity");
    expect(first).toBe("0,0,10");
    expect(csv.split("\n")[2]).toBe("1,0.5,20");
  });

  it("omits the calibrated column when there is no calibration to give", () => {
    const csv = profileCsvText({ ...base, pixel_size: 1, unit: "px" });
    expect(csv.split("\n")[0]).toBe("depth_px,intensity");
    expect(csv.split("\n")[1]).toBe("0,10");
  });

  it("stops at the shorter of the two arrays rather than emitting undefined", () => {
    const csv = profileCsvText({
      ...base, pixel_size: 1, unit: "px",
      depth_pos: [0, 1, 2, 3], depth_profile: [10, 20],
    });
    expect(csv.split("\n")).toHaveLength(3);   // header + 2 rows
    expect(csv).not.toContain("undefined");
  });
});
