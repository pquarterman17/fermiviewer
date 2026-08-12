import { describe, expect, it } from "vitest";

import type { FourDMeta } from "../../../lib/api";
import { probeLabel } from "./FourDPatternPanel";

function fourdMeta(scanAxes: FourDMeta["scan_axes"]): FourDMeta {
  return {
    id: "d1",
    name: "d1.mib",
    is_fourd: true,
    source: null,
    scan_shape: [4, 5],
    det_shape: [64, 64],
    dtype: "uint16",
    scan_axes: scanAxes,
    det_axes: [
      { scale: 1, origin: 0, units: "" },
      { scale: 1, origin: 0, units: "" },
    ],
    nav_available: true,
  n_frames: 0,
  scan_shape_from_file: true,
  scan_shape_options: [],
  };
}

describe("probeLabel", () => {
  it("shows the mean-pattern label when no probe is set", () => {
    expect(probeLabel(null, null)).toBe("mean pattern");
  });

  it("shows a bare pixel position without dataset metadata", () => {
    expect(probeLabel({ y: 2, x: 3 }, null)).toBe("probe (2, 3) px");
  });

  it("shows a bare pixel position when the scan axes are uncalibrated", () => {
    const meta = fourdMeta([
      { scale: 1, origin: 0, units: "" },
      { scale: 1, origin: 0, units: "" },
    ]);
    expect(probeLabel({ y: 2, x: 3 }, meta)).toBe("probe (2, 3) px");
  });

  it("appends calibrated scan-space units when the axes are calibrated", () => {
    const meta = fourdMeta([
      { scale: 0.5, origin: 0, units: "nm" },
      { scale: 0.5, origin: 0, units: "nm" },
    ]);
    expect(probeLabel({ y: 2, x: 4 }, meta)).toBe(
      "probe (2, 4) px = (1.000, 2.000) nm",
    );
  });

  it("honors AxisCal's (index - origin) * scale convention", () => {
    const meta = fourdMeta([
      { scale: 2, origin: 10, units: "nm" },
      { scale: 2, origin: 10, units: "nm" },
    ]);
    // (5 - 10) * 2 = -10
    expect(probeLabel({ y: 5, x: 5 }, meta)).toBe(
      "probe (5, 5) px = (-10.00, -10.00) nm",
    );
  });
});
