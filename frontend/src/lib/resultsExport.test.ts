import { describe, expect, it } from "vitest";

import { exportBaseName, tableToCsv, tableToJson } from "./resultsExport";

const COLS = ["element", "at%"];
const ROWS = [
  ["Fe", 62.5],
  ["O", 37.5],
];
const META = {
  imageName: "scan.dm4",
  analysis: "EDS quantification",
  params: { kv: 200 },
  timestamp: "2026-06-21T00:00:00Z",
};

describe("tableToCsv", () => {
  it("emits provenance header + column row + data rows", () => {
    const csv = tableToCsv(COLS, ROWS, META);
    const lines = csv.trimEnd().split("\n");
    expect(lines[0]).toBe("# fermiviewer results export");
    expect(lines).toContain("# analysis: EDS quantification");
    expect(lines).toContain("# image: scan.dm4");
    expect(lines).toContain("# exported: 2026-06-21T00:00:00Z");
    expect(lines).toContain("# kv: 200");
    expect(lines).toContain("element,at%");
    expect(lines).toContain("Fe,62.5");
    expect(lines).toContain("O,37.5");
  });

  it("rounds numbers to 7 sig figs and blanks NaN/null", () => {
    const csv = tableToCsv(["x", "y"], [[1 / 3, NaN], [null, 2]]);
    expect(csv).toContain("0.3333333,");
    expect(csv).toContain("0.3333333,\n"); // NaN → empty
    expect(csv).toContain(",2");
  });

  it("quotes fields containing commas/quotes", () => {
    const csv = tableToCsv(["label"], [['a,b'], ['he said "hi"']]);
    expect(csv).toContain('"a,b"');
    expect(csv).toContain('"he said ""hi"""');
  });

  it("works with no meta (no provenance header)", () => {
    const csv = tableToCsv(COLS, ROWS);
    expect(csv.startsWith("element,at%")).toBe(true);
  });
});

describe("tableToJson", () => {
  it("builds provenance + row objects keyed by column", () => {
    const j = JSON.parse(tableToJson(COLS, ROWS, META));
    expect(j.provenance.analysis).toBe("EDS quantification");
    expect(j.provenance.image).toBe("scan.dm4");
    expect(j.provenance.params.kv).toBe(200);
    expect(j.columns).toEqual(["element", "at%"]);
    expect(j.rows).toEqual([
      { element: "Fe", "at%": 62.5 },
      { element: "O", "at%": 37.5 },
    ]);
  });
});

describe("exportBaseName", () => {
  it("strips the extension; falls back to 'results'", () => {
    expect(exportBaseName("scan.dm4")).toBe("scan");
    expect(exportBaseName("a.b.tif")).toBe("a.b");
    expect(exportBaseName(undefined)).toBe("results");
  });
});
