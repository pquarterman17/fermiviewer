import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { DEFAULT_FORCE_SETTINGS, type ForceMapsResult, type ForceMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => ({
  ...await importActual<typeof import("../../lib/api")>(), runJob: vi.fn(), startForceMapsJob: vi.fn(),
}));
vi.mock("../../lib/resultsExport", async (importActual) => ({
  ...await importActual<typeof import("../../lib/resultsExport")>(),
  downloadCsv: vi.fn(), downloadJson: vi.fn(),
}));

import { runJob } from "../../lib/api";
import { downloadCsv, downloadJson } from "../../lib/resultsExport";
import AfmForceMapPanel from "./AfmForceMapPanel";

const meta: ForceMeta = {
  id: "map", name: "map.nid", is_force: true, parser: "nanosurf", n_curves: 4,
  grid: [2, 2], map_pitch_nm: [10, 10], spring_constant: 1, invols: 50,
  deflection_unit: "nm", z_source: "Z sensor",
};

const summary = { n: 3, median: 2e6, mad: 1e5, q05: 1e6, q95: 3e6 };
const result: ForceMapsResult = {
  n: 4, failed: 0, accepted: 3, rejected: 1, images: [],
  units: { youngs_modulus: "Pa" },
  summaries: Object.fromEntries([
    "youngs_modulus", "adhesion", "contact_z", "max_force", "fit_r2", "fit_rms",
    "fit_points", "residual_lag1",
  ].map((key) => [key, summary])) as ForceMapsResult["summaries"],
  table: {
    youngs_modulus: [1e6, 2e6, null, 3e6], adhesion: [1, 2, null, 3],
    contact_z: [1, 2, null, 3], max_force: [1, 2, null, 3], fit_r2: [.99, .97, null, .95],
    fit_rms: [.1, .2, null, .3], fit_points: [20, 20, null, 20],
    residual_lag1: [.1, .2, null, .3], accepted: [true, true, false, true],
  },
  grids: {
    youngs_modulus: [[1e6, 2e6], [null, 3e6]], adhesion: [[1, 2], [null, 3]],
    contact_z: [[1, 2], [null, 3]], max_force: [[1, 2], [null, 3]],
    fit_r2: [[.99, .97], [null, .95]], fit_rms: [[.1, .2], [null, .3]],
    fit_points: [[20, 20], [null, 20]], residual_lag1: [[.1, .2], [null, .3]],
    accepted: [[true, true], [false, true]],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  useViewer.setState({ images: {}, order: [], activeId: null, status: "" });
});

it("shows progress, links map pixels to curves, and exports complete grids", async () => {
  vi.mocked(runJob).mockImplementation(async (_start, onProgress) => {
    onProgress(0.5, "fitting curve 2/4");
    return result;
  });
  const select = vi.fn();
  render(<AfmForceMapPanel meta={meta} settings={DEFAULT_FORCE_SETTINGS} onBusyChange={vi.fn()} onSelectCurve={select} />);
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Analyse map" })); });
  expect(await screen.findByText("3 accepted")).toBeVisible();
  const cells = screen.getAllByRole("gridcell");
  expect(cells[2]).toHaveClass("rejected");
  fireEvent.click(cells[2]);
  expect(select).toHaveBeenCalledWith(2);
  fireEvent.click(screen.getByRole("button", { name: "Export grids + provenance" }));
  expect(downloadJson).toHaveBeenCalledWith("map_force_map.json", expect.stringContaining('"grids"'));
  fireEvent.click(screen.getByRole("button", { name: "Export numeric CSV" }));
  expect(downloadCsv).toHaveBeenCalledWith(
    "map_force_map.csv",
    expect.stringMatching(/curve,row,column,x_nm,y_nm[\s\S]*4,2,2,10,10/),
  );
});

it("cancels an active map job", async () => {
  vi.mocked(runJob).mockImplementation((_start, onProgress, _poll, signal) => {
    onProgress(0.25, "fitting curve 1/4");
    return new Promise((_resolve, reject) => signal?.addEventListener("abort", () => reject(new Error("cancelled"))));
  });
  const busy = vi.fn();
  render(<AfmForceMapPanel meta={meta} settings={DEFAULT_FORCE_SETTINGS} onBusyChange={busy} onSelectCurve={vi.fn()} />);
  fireEvent.click(screen.getByRole("button", { name: "Analyse map" }));
  expect(await screen.findByText(/25%/)).toBeVisible();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Cancel" })); });
  expect(busy).toHaveBeenLastCalledWith(false);
});
