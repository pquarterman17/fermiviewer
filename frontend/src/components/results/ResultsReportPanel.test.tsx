import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, buildPersistedResultsReport: vi.fn() };
});
vi.mock("../../lib/resultsExport", () => ({ downloadJson: vi.fn(), downloadText: vi.fn() }));

import { buildPersistedResultsReport, type PersistedResultRecord, type ResultsReport } from "../../lib/api";
import { downloadJson, downloadText } from "../../lib/resultsExport";
import ResultsReportPanel from "./ResultsReportPanel";

const result = (id: string): PersistedResultRecord => ({
  id, analysis: "measure.profile", label: `Profile ${id}`, created_at: "2026-08-28T12:00:00Z",
  status: "completed", source_ids: [`source-${id}`], params: {},
  outputs: [{ kind: "scalar", name: "length", data: { value: id === "a" ? 10 : 20, unit: "nm" } }],
});
const RESULTS = [result("a"), result("b")];
const report = (ids: string[]): ResultsReport => ({
  version: 1, generated_at: "2026-08-28T13:00:00Z", app_version: "0.2.0", warnings: [], calibration: [],
  methods: "Profile method", results: ids.map((id) => ({ ...result(id), methods: "Profile method" })),
});

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(buildPersistedResultsReport).mockImplementation(async (ids) => report(ids));
});

describe("ResultsReportPanel", () => {
  it("preserves the authored result order when building a preview", async () => {
    render(<ResultsReportPanel results={RESULTS} nameOf={(id) => `${id}.dm4`} />);
    fireEvent.click(screen.getByRole("button", { name: "Move Profile b up" }));
    fireEvent.click(screen.getByRole("button", { name: "Build report preview" }));
    await waitFor(() => expect(buildPersistedResultsReport).toHaveBeenCalledWith(["b", "a"]));
    expect(screen.getByTitle("Analysis report preview")).toBeVisible();
  });

  it("uses output selections in the generated document and exports both formats", async () => {
    render(<ResultsReportPanel results={RESULTS} nameOf={(id) => `${id}.dm4`} />);
    fireEvent.click(screen.getByRole("button", { name: "Build report preview" }));
    const frame = await screen.findByTitle("Analysis report preview");
    expect(frame.getAttribute("srcdoc")).toContain("<div>10<small>");
    expect(frame.getAttribute("srcdoc")).toContain("<div>20<small>");

    fireEvent.click(screen.getByRole("button", { name: "Export HTML" }));
    expect(downloadText).toHaveBeenCalledWith("microscopy-analysis-report.html", expect.stringContaining("<!doctype html>"), "text/html");
    fireEvent.click(screen.getByRole("button", { name: "Manifest JSON" }));
    expect(downloadJson).toHaveBeenCalledWith("microscopy-analysis-report-manifest.json", expect.stringContaining('"version": 1'));
  });

  it("prevents a selected result from being exported without scientific outputs", () => {
    render(<ResultsReportPanel results={RESULTS} nameOf={(id) => id} />);
    fireEvent.click(screen.getAllByRole("checkbox", { name: /lengthscalar/ })[0]);
    expect(screen.getByText("Select at least one scientific output for every included result.")).toBeVisible();
    expect(screen.getByRole("button", { name: "Build report preview" })).toBeDisabled();
  });

  it("disables report generation when the selection is empty", () => {
    render(<ResultsReportPanel results={RESULTS} nameOf={(id) => id} />);
    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    expect(screen.getByRole("button", { name: "Build report preview" })).toBeDisabled();
  });
});
