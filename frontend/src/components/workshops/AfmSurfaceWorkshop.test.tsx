// The ISO 25178 table: every parameter grouped once, units carried into
// the export rows, missing values shown as a dash.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ISO_PARAMS, type AfmSurfaceResult, type ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, afmSurface: vi.fn() };
});
// plots are not under test; jsdom has no canvas for uPlot
vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

import { afmSurface } from "../../lib/api";
import AfmSurfaceWorkshop, { formatParam, ISO_GROUPS, surfaceRows } from "./AfmSurfaceWorkshop";

function image(id: string): ImageMeta {
  return {
    id, name: `${id}.spm`, kind: "image", shape: [64, 64], dtype: "float32",
    pixel_size: 2, pixel_unit: "nm", value_unit: "nm", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null, meta: {},
  };
}

function surface(sa: number): AfmSurfaceResult {
  const params = Object.fromEntries(ISO_PARAMS.map((k) => [k, sa])) as AfmSurfaceResult["params"];
  const units = Object.fromEntries(ISO_PARAMS.map((k) => [k, "nm"])) as AfmSurfaceResult["units"];
  return {
    params, units, z_unit: "nm", lateral_unit: "nm", n_pixels: 4096, level: "plane",
    roi: null, slopes_calibrated: true,
    psd: { frequency: [], power: [] },
    height_hist: { height: [], percent: [] },
    slope_hist: { angle: [], percent: [] },
  };
}

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [], measures: {} });
});

describe("AfmSurfaceWorkshop", () => {
  it("drops a result that lands after the active image changed", async () => {
    let resolve!: (r: AfmSurfaceResult) => void;
    vi.mocked(afmSurface).mockReturnValue(new Promise((r) => { resolve = r; }));
    useViewer.getState().ingest([image("a"), image("b")]);
    useViewer.getState().setActive("a");
    render(<AfmSurfaceWorkshop />);

    fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve(surface(7)));

    expect(screen.queryByText("7.000 nm")).toBeNull();
    expect(screen.getByRole("button", { name: "Analyze" })).not.toBeDisabled();
  });

  it("shows the result of the latest run", async () => {
    vi.mocked(afmSurface).mockResolvedValue(surface(3));
    useViewer.getState().ingest([image("a")]);
    useViewer.getState().setActive("a");
    render(<AfmSurfaceWorkshop />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    });
    expect(screen.getAllByText("3.000 nm").length).toBeGreaterThan(0);
  });
});

describe("AfmSurfaceWorkshop helpers", () => {
  it("groups every ISO parameter exactly once", () => {
    expect(ISO_GROUPS.flatMap((g) => g.keys).sort()).toEqual([...ISO_PARAMS].sort());
  });

  it("formats values with units and dashes for missing ones", () => {
    expect(formatParam(1.23456, "nm")).toBe("1.235 nm");
    expect(formatParam(null, "%")).toBe("—");
    expect(formatParam(0.5, "")).toBe("0.5000");
  });

  it("exports one row per parameter with its unit", () => {
    const params = Object.fromEntries(ISO_PARAMS.map((k) => [k, 1])) as AfmSurfaceResult["params"];
    const units = Object.fromEntries(ISO_PARAMS.map((k) => [k, k === "Sa" ? "nm" : ""])) as
      AfmSurfaceResult["units"];
    const rows = surfaceRows({ params, units } as AfmSurfaceResult);
    expect(rows).toHaveLength(ISO_PARAMS.length);
    expect(rows[0].slice(0, 3)).toEqual(["Sa", 1, "nm"]);
  });
});
