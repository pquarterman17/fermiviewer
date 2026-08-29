import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, comparePersistedResults: vi.fn() };
});

import { comparePersistedResults, type PersistedResultRecord } from "../../lib/api";
import ResultsComparePanel from "./ResultsComparePanel";

const result = (id: string, source: string, iron: number): PersistedResultRecord => ({
  id,
  analysis: "eds.quantify",
  label: `Quantification ${id}`,
  created_at: "2026-08-28T12:00:00Z",
  status: "completed",
  source_ids: [source],
  outputs: [
    { kind: "scalar", name: "Fe", data: { value: iron, sigma: 0.5, unit: "at%" } },
    { kind: "table", name: "composition", data: { columns: ["element"] } },
  ],
});

const RESULTS = [result("ref", "a", 51.2), result("match", "b", 48.8), result("wrong", "c", 10)];

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(comparePersistedResults).mockResolvedValue({
    reference_id: "ref",
    outputs: ["Fe", "composition"],
    compatible: [{
      id: "match",
      outputs: ["Fe", "composition"],
      calibration_agreement: {
        verified: false, agrees: true, shared_sources: [], reference_only: ["a"],
        candidate_only: ["b"], differences: [],
      },
    }],
    rejected: [{ id: "wrong", code: "output_unit_mismatch", message: "Fe uses incompatible units" }],
    notes: ["Calibration agreement was not verified across different sources."],
  });
});

describe("ResultsComparePanel", () => {
  it("requires two completed results", () => {
    render(<ResultsComparePanel results={[RESULTS[0]]} nameOf={(id) => `${id}.dm4`} />);
    expect(screen.getByText("Two completed results are needed")).toBeVisible();
    expect(comparePersistedResults).not.toHaveBeenCalled();
  });

  it("renders compatible scalar values, non-scalar outputs, and honest review notes", async () => {
    render(<ResultsComparePanel results={RESULTS} nameOf={(id) => `${id}.dm4`} />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Shared scientific outputs" })).toBeVisible());
    expect(comparePersistedResults).toHaveBeenCalledWith("ref", undefined, expect.any(AbortSignal));
    expect(screen.getByText("51.2")).toBeVisible();
    expect(screen.getByText("48.8")).toBeVisible();
    expect(screen.getAllByText("table")).toHaveLength(2);
    expect(screen.getByText("Calibration not verified")).toBeVisible();

    fireEvent.click(screen.getByText(/Compatibility review/));
    expect(screen.getByText(/Calibration agreement was not verified/)).toBeVisible();
    expect(screen.getByText(/Fe uses incompatible units/)).toBeVisible();
  });

  it("removes an unchecked candidate from the comparison matrix", async () => {
    render(<ResultsComparePanel results={RESULTS} nameOf={(id) => `${id}.dm4`} />);
    const checkbox = await screen.findByRole("checkbox");
    expect(screen.getByText("1 selected")).toBeVisible();
    fireEvent.click(checkbox);
    expect(screen.getByText("0 selected")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Shared scientific outputs" })).toBeNull();
  });
});
