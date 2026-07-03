// Unit tests for the EDS model-fit CSV serialiser (#11).

import { describe, expect, it } from "vitest";

import type { EdsPeakfitResult, EdsZetaResult } from "./api";
import { edsModelFitToCsv } from "./edsQuantCsv";

const BASE: EdsPeakfitResult = {
  energy: [0, 1],
  spectrum: [0, 0],
  model: [0, 0],
  elements: [
    {
      symbol: "Fe", line: "K", energy_kev: 6.404,
      net_area: 4000.123456, net_area_error: 12.3, curve: null,
    },
    {
      symbol: "Cu", line: "K", energy_kev: 8.048,
      net_area: 6000, net_area_error: 15.9, curve: null,
    },
  ],
  reduced_chi2: 1.25,
  success: true,
  quant: {
    elements: ["Fe", "Cu"],
    atomic_percent: [43.2, 56.8],
    atomic_percent_error: [0.5, 0.5],
    weight_percent: [40, 60],
    weight_percent_error: [0.4, 0.6],
  },
};

describe("edsModelFitToCsv", () => {
  it("serialises the Cliff-Lorimer table with provenance", () => {
    const csv = edsModelFitToCsv(BASE, { imageName: "sample.dm4" });
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("# fermiviewer EDS model-fit export");
    expect(lines).toContain("# image: sample.dm4");
    expect(lines).toContain("# method: cliff-lorimer");
    expect(lines).toContain("# reduced_chi2: 1.25");
    expect(lines).toContain(
      "element,line,energy_kev,net_area,net_area_error," +
        "atomic_percent,atomic_percent_error,weight_percent,weight_percent_error",
    );
    expect(lines).toContain("Fe,K,6.404,4000.123,12.3,43.2,0.5,40,0.4");
    expect(lines).toContain("Cu,K,8.048,6000,15.9,56.8,0.5,60,0.6");
  });

  it("omits quant columns' values without a quant block", () => {
    const csv = edsModelFitToCsv(
      { ...BASE, quant: undefined },
      { imageName: "x" },
    );
    expect(csv).toContain("Fe,K,6.404,4000.123,12.3,,,,");
  });

  it("emits ζ mass-thickness/thickness/dose provenance (#7)", () => {
    const zeta: EdsZetaResult = {
      ...BASE,
      quant: {
        ...BASE.quant!,
        mass_thickness_kg_m2: 2e-4,
        mass_thickness_error_kg_m2: 1e-6,
        mass_thickness_ug_cm2: 20,
        thickness_nm: 40,
        absorption_factors: [1.2, 1.1],
        zeta_factors: [900, 950],
        dose_electrons: 6.2415e11,
      },
    };
    const csv = edsModelFitToCsv(zeta, { imageName: "x" });
    expect(csv).toContain("# method: zeta-factor");
    expect(csv).toContain("# mass_thickness_kg_m2: 0.0002 ± 0.000001");
    expect(csv).toContain("# mass_thickness_ug_cm2: 20");
    expect(csv).toContain("# thickness_nm: 40");
    expect(csv).toContain("# dose_electrons: 624150000000");
  });

  it("appends the artifact trail as commented rows (#8)", () => {
    const withArts: EdsPeakfitResult = {
      ...BASE,
      artifacts: [
        {
          name: "esc_Cu", label: "Cu esc", kind: "escape",
          energy_kev: 6.308, status: "modeled", area: 60, area_error: null,
        },
        {
          name: "sum_Fe_Cu", label: "Fe+Cu", kind: "sum",
          energy_kev: 14.452, status: "measured", area: 30, area_error: 2,
        },
      ],
    };
    const csv = edsModelFitToCsv(withArts, { imageName: "x" });
    expect(csv).toContain("# artifact,kind,energy_kev,status,area,area_error");
    expect(csv).toContain("# Cu esc,escape,6.308,modeled,60,");
    expect(csv).toContain("# Fe+Cu,sum,14.452,measured,30,2");
  });
});
