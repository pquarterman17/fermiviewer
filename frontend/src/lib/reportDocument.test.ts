import { describe, expect, it } from "vitest";

import type { ResultsReport } from "./api";
import { resultsReportHtml } from "./reportDocument";

const REPORT: ResultsReport = {
  version: 1,
  generated_at: "2026-08-28T12:00:00Z",
  app_version: "0.2.0",
  warnings: ["review <this>"],
  methods: "Measured a profile.",
  calibration: [{ image_id: "img", result_ids: ["r1"], consistent: true, variants: [{
    source: null, result_ids: ["r1"], axes: [{ index: 0, scale: 0.5, origin: 0, units: "nm", calibrated: true }],
  }] }],
  results: [{
    id: "r1", analysis: "measure.profile", label: "Profile <A>", created_at: "2026-08-28T11:00:00Z",
    status: "completed", source_ids: ["img"], params: { width: 3 }, methods: "Measured a profile.",
    outputs: [
      { kind: "scalar", name: "length", data: { value: 12.5, unit: "nm" }, caption: "Profile length" },
      { kind: "curve", name: "profile", values: [[0, 1], [1, 3], [2, 2]], values_inlined: true },
      { kind: "table", name: "hidden_table", data: { columns: ["x"], rows: [[1]] } },
    ],
  }],
};

describe("resultsReportHtml", () => {
  it("renders the selected outputs and print-ready scientific sections", () => {
    const html = resultsReportHtml(REPORT, {
      title: "Comparison <report>", note: "Annealed & measured", sourceNames: { img: "sample.dm4" },
      outputNamesByResult: { r1: ["length", "profile"] }, includeMethods: true,
      includeCalibration: true, includeWarnings: true,
    });
    expect(html).toContain("Comparison &lt;report&gt;");
    expect(html).toContain("Annealed &amp; measured");
    expect(html).toContain("12.5");
    expect(html).toContain("<polyline");
    expect(html).not.toContain("hidden_table");
    expect(html).toContain("Calibration summary");
    expect(html).toContain("Methods");
    expect(html).toContain("@media print");
  });

  it("escapes record and warning content rather than creating markup", () => {
    const html = resultsReportHtml(REPORT, {
      title: "Report", note: "", sourceNames: {}, outputNamesByResult: { r1: [] },
      includeMethods: false, includeCalibration: false, includeWarnings: true,
    });
    expect(html).toContain("Profile &lt;A&gt;");
    expect(html).toContain("review &lt;this&gt;");
    expect(html).not.toContain("<A>");
  });

  it("renders failure, degraded storage, units, and timestamps explicitly", () => {
    const changed: ResultsReport = { ...REPORT, results: [{
      ...REPORT.results[0], status: "failed", error: "fit failed", missing_members: ["arrays/lost.npy"],
      outputs: [
        { kind: "scalar", name: "count", data: { value: 123456789, unit: "" }, caption: "Count caption" },
        { kind: "table", name: "composition", data: { columns: ["atomic_pct", "ratio"], units: ["at%", ""], dimensionless: true }, values: [[12.5, null]], values_inlined: true },
        { kind: "curve", name: "lost", member: "arrays/lost.npy", values: null, values_inlined: false, shape: null, dtype: null },
      ],
    }] };
    const html = resultsReportHtml(changed, {
      title: "Report", note: "", sourceNames: {}, outputNamesByResult: { r1: ["count", "composition", "lost"] },
      includeMethods: false, includeCalibration: false, includeWarnings: false,
    });
    expect(html).toContain("FAILED</strong> — fit failed");
    expect(html).toContain("DEGRADED");
    expect(html).toContain("123456789");
    expect(html).toContain("unit not recorded");
    expect(html).toContain("atomic_pct<small>at%</small>");
    expect(html).toContain("ratio<small>dimensionless</small>");
    expect(html).toContain("not finite</td>");
    expect(html).toContain("missing or unreadable");
    expect(html).toContain("2026-08-28T11:00:00.000Z");
    expect(html).toContain("Result r1");
    expect(html).toContain("Count caption");
  });

  it("distinguishes empty inline data from a cited project member", () => {
    const changed: ResultsReport = { ...REPORT, results: [{ ...REPORT.results[0], outputs: [
      { kind: "table", name: "empty", values: [], values_inlined: true, shape: [0, 2], dtype: "float64" },
      { kind: "fit", name: "large_fit", member: "arrays/fit.npy", values: null, values_inlined: false, shape: [5000, 2], dtype: "float64" },
    ] }] };
    const html = resultsReportHtml(changed, {
      title: "Report", note: "", sourceNames: {}, outputNamesByResult: { r1: ["empty", "large_fit"] },
      includeMethods: false, includeCalibration: false, includeWarnings: false,
    });
    expect(html).toContain("0 rows were recorded");
    expect(html).toContain("cited as project member arrays/fit.npy (5000 × 2, float64)");
  });
});
