import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { PersistedResultRecord } from "../../lib/api";
import PersistedResultCard from "./PersistedResultCard";

const RESULT: PersistedResultRecord = {
  id: "eds-001",
  analysis: "eds.quantify",
  label: "Whole-particle composition",
  created_at: "2026-08-22T20:00:00Z",
  app_version: "0.1.32",
  status: "completed",
  source_ids: ["img1"],
  regions: [{ id: "roi1", kind: "polygon", pts: [] }],
  params: { method: "cliff_lorimer", beam_kv: 200 },
  calibration: [{
    image_id: "img1",
    axes: [
      { scale: 0.5, origin: 0, units: "nm" },
      { scale: 0.5, origin: 0, units: "nm" },
    ],
    source: "fei",
  }],
  warnings: ["O K has low counts; review the fitted background."],
  outputs: [
    { kind: "scalar", name: "Fe", data: { value: 61.24, sigma: 1.3, unit: "at%" } },
    { kind: "scalar", name: "O", data: { value: 38.76, sigma: 1.3, unit: "at%" } },
    { kind: "table", name: "composition", member: "results/eds-001/2.npy" },
  ],
  missing_members: [],
};

describe("PersistedResultCard", () => {
  it("presents an EDS result as values, context, warnings and provenance", () => {
    const select = vi.fn();
    render(
      <PersistedResultCard
        result={RESULT}
        sources={[{ id: "img1", name: "particle.dm4", available: true }]}
        onSelectSource={select}
      />,
    );

    expect(screen.getByRole("heading", { name: "Whole-particle composition" })).toBeVisible();
    expect(screen.getByText("Complete")).toBeVisible();
    expect(screen.getByText("61.24")).toBeVisible();
    expect(screen.getAllByText(/± 1.3/)).toHaveLength(2);
    expect(screen.getAllByText("at%")).toHaveLength(2);
    expect(screen.getByText("cliff lorimer · 200 kV")).toBeVisible();
    expect(screen.getByText("1 snapshotted region")).toBeVisible();
    expect(screen.getByText(/low counts/)).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "particle.dm4" }));
    expect(select).toHaveBeenCalledWith("img1");

    fireEvent.click(screen.getByText("Provenance"));
    expect(screen.getByText("eds-001")).toBeVisible();
    expect(screen.getByText("0.1.32")).toBeVisible();
  });

  it("makes a lost member visually explicit without hiding intact metadata", () => {
    render(
      <PersistedResultCard
        result={{ ...RESULT, missing_members: ["results/eds-001/2.npy"] }}
        sources={[{ id: "img1", name: "particle.dm4", available: true }]}
      />,
    );
    expect(screen.getByText("Degraded")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Some saved data is unavailable");
    expect(screen.getByText("Whole-particle composition")).toBeVisible();
  });

  it.each([
    ["failed", "Analysis failed", "matrix was singular"],
    ["cancelled", "Analysis cancelled", "cancelled by user"],
  ] as const)("explains a %s record", (status, title, error) => {
    render(
      <PersistedResultCard
        result={{ ...RESULT, status, error, outputs: [] }}
        sources={[]}
      />,
    );
    expect(screen.getByText(title)).toBeVisible();
    expect(screen.getByText(error)).toBeVisible();
    expect(screen.getByText("No scientific outputs")).toBeVisible();
  });
});
