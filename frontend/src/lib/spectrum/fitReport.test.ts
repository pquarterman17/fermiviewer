// Unit tests for the spectral fit-report CSV serialiser
// (ANALYSIS_PRESENTATION_PLAN.md #7 / audit R8).

import { describe, expect, it } from "vitest";

import type { EdsPeakfitResult, EdsZetaResult, EelsFitResult } from "../api";
import { edsFitReportToCsv, eelsFitReportToCsv } from "./fitReport";

const EELS: EelsFitResult = {
  energy: [400, 401, 402],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  background: [1, 1, 1],
  edges: [
    {
      element: "O",
      shell: "K",
      onset_ev: 532,
      atomic_percent: 66.7,
      atomic_percent_error: 1.2,
      amplitude: 4000.123456,
      amplitude_error: 12.3,
      curve: [1, 2, 3],
    },
    {
      element: "Mn",
      shell: "L",
      onset_ev: 640,
      atomic_percent: 33.3,
      atomic_percent_error: 1.1,
      amplitude: 2000,
      amplitude_error: 8.5,
      curve: [1, 2, 3],
    },
  ],
  reduced_chi2: 1.25,
  r_squared: 0.987,
  success: true,
  fit_range: [452, 950],
  model_sigma: null,
};

describe("eelsFitReportToCsv", () => {
  it("serialises the fit-window/χ²ᵣ/R² header and one row per edge", () => {
    const csv = eelsFitReportToCsv(EELS, { imageName: "sample.dm4" });
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("# fermiviewer EELS fit report");
    expect(lines).toContain("# image: sample.dm4");
    expect(lines).toContain("# fit_range_ev: 452-950");
    expect(lines).toContain("# reduced_chi2: 1.25");
    expect(lines).toContain("# r_squared: 0.987");
    expect(lines).toContain("# converged: true");
    expect(lines).toContain(
      "element,shell,onset_ev,amplitude,amplitude_error," +
        "atomic_percent,atomic_percent_error",
    );
    // pinned number formatting: matches edsQuantCsv's precision-7 convention
    // exactly (4000.123456 → 4000.123, same case as edsQuantCsv.test.ts)
    expect(lines).toContain("O,K,532,4000.123,12.3,66.7,1.2");
    expect(lines).toContain("Mn,L,640,2000,8.5,33.3,1.1");
  });

  it("flags a non-converged fit", () => {
    const csv = eelsFitReportToCsv(
      { ...EELS, success: false },
      { imageName: "x" },
    );
    expect(csv).toContain("# converged: false");
  });
});

const EDS: EdsPeakfitResult = {
  energy: [0, 1, 2],
  spectrum: [10, 20, 30],
  model: [9, 19, 31],
  model_sigma: null,
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
  reduced_chi2: 2.5,
  r_squared: 0.95,
  success: true,
  quant: {
    elements: ["Fe", "Cu"],
    atomic_percent: [43.2, 56.8],
    atomic_percent_error: [0.5, 0.5],
    weight_percent: [40, 60],
    weight_percent_error: [0.4, 0.6],
  },
};

describe("edsFitReportToCsv", () => {
  it("serialises the energy-range/χ²ᵣ/R² header and one row per element", () => {
    const csv = edsFitReportToCsv(EDS, { imageName: "eds.bcf" });
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("# fermiviewer EDS fit report");
    expect(lines).toContain("# image: eds.bcf");
    expect(lines).toContain("# method: cliff-lorimer");
    expect(lines).toContain("# energy_range_kev: 0-2");
    expect(lines).toContain("# reduced_chi2: 2.5");
    expect(lines).toContain("# r_squared: 0.95");
    expect(lines).toContain("# converged: true");
    expect(lines).toContain(
      "element,line,energy_kev,net_area,net_area_error," +
        "atomic_percent,atomic_percent_error,weight_percent,weight_percent_error",
    );
    expect(lines).toContain("Fe,K,6.404,4000.123,12.3,43.2,0.5,40,0.4");
    expect(lines).toContain("Cu,K,8.048,6000,15.9,56.8,0.5,60,0.6");
  });

  it("omits quant column values without a quant block, without holes", () => {
    const csv = edsFitReportToCsv(
      { ...EDS, quant: undefined },
      { imageName: "x" },
    );
    const lines = csv.trimEnd().split("\n");
    expect(lines).toContain("# method: none");
    // net area/error still populated; at%/wt% columns blank but present —
    // every row has the same 9 comma-separated fields, no missing commas
    expect(lines).toContain("Fe,K,6.404,4000.123,12.3,,,,");
    expect(lines.find((l) => l.startsWith("Fe,"))?.split(",")).toHaveLength(9);
  });

  it("labels the ζ-factor method for a zeta result", () => {
    const zeta: EdsZetaResult = {
      ...EDS,
      quant: {
        ...EDS.quant!,
        mass_thickness_kg_m2: 2e-4,
        mass_thickness_error_kg_m2: 1e-6,
        mass_thickness_ug_cm2: 20,
        thickness_nm: 40,
        absorption_factors: [1.2, 1.1],
        zeta_factors: [900, 950],
        dose_electrons: 6.2415e11,
      },
    };
    const csv = edsFitReportToCsv(zeta, { imageName: "x" });
    expect(csv).toContain("# method: zeta-factor");
    // the quant columns are still just at%/wt% ± σ here — mass-thickness
    // lives in the separate quant-table export (lib/edsQuantCsv.ts)
    expect(csv).toContain("Fe,K,6.404,4000.123,12.3,43.2,0.5,40,0.4");
  });
});
