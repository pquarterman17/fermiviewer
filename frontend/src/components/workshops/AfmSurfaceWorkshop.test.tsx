// The ISO 25178 table: every parameter grouped once, units carried into
// the export rows, missing values shown as a dash.
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ISO_PARAMS, type AfmSurfaceResult, type ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import { useWorkshop } from "../../store/workshop";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return { ...actual, afmSurface: vi.fn(), afmMap: vi.fn() };
});
vi.mock("../../lib/resultsExport", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/resultsExport")>();
  return { ...actual, downloadCsv: vi.fn(), downloadJson: vi.fn() };
});
// plots are not under test; jsdom has no canvas for uPlot
vi.mock("uplot", () => ({
  default: class {
    destroy() {}
  },
}));

import { afmMap, afmSurface } from "../../lib/api";
import { downloadJson } from "../../lib/resultsExport";
import AfmSurfaceWorkshop, { formatParam, ISO_GROUPS, surfaceRows } from "./AfmSurfaceWorkshop";

function image(id: string): ImageMeta {
  return {
    id, name: `${id}.spm`, kind: "image", shape: [64, 64], dtype: "float32",
    pixel_size: 2, pixel_unit: "nm", value_unit: "nm", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser: "nanoscope", channel: "Height", spm_channel_kind: "height" },
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

const savedRoi = {
  id: "r1", name: "Terrace", kind: "roi" as const, createdAt: "2026-01-01T00:00:00Z",
  pts: [{ x: 4, y: 4 }, { x: 20, y: 20 }],
};

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {}, order: [], activeId: null, selected: [], measures: {},
    tools: [], captureMode: "none",
  });
});

describe("AfmSurfaceWorkshop", () => {
  it("refuses a non-height image even if the workshop remains open", () => {
    const phase = image("phase");
    phase.value_unit = "deg";
    phase.meta = { parser: "nanoscope", channel: "Phase", spm_channel_kind: "other" };
    useViewer.getState().ingest([phase]);
    render(<AfmSurfaceWorkshop />);

    expect(screen.getByText("Select a 2D height map.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Analyze" })).toBeNull();
  });

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
    expect(screen.getByRole("heading", { name: "Surface summary" })).toBeVisible();
    expect(screen.getByText(`${ISO_PARAMS.length} metrics`)).toBeVisible();
  });

  it("guides the workflow and creates maps without leaving the source", async () => {
    vi.mocked(afmSurface).mockResolvedValue(surface(3));
    vi.mocked(afmMap).mockResolvedValue({ ...image("psd"), name: "a 2-D PSD" });
    useViewer.getState().ingest([image("a")]);
    useViewer.getState().setActive("a");
    render(<AfmSurfaceWorkshop />);

    expect(screen.getByRole("heading", { name: "Analysis path" })).toBeVisible();
    expect(screen.getByText("Not analyzed")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Draw ROI" }));
    expect(useViewer.getState().captureMode).toBe("roi");

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Create 2-D PSD" })));
    expect(afmMap).toHaveBeenCalledWith("a", "psd", { level: "plane", roi: null });
    expect(useViewer.getState().images.psd.name).toBe("a 2-D PSD");
    expect(useViewer.getState().activeId).toBe("a");
    expect(screen.getByText("Ready in Library")).toBeVisible();
    expect(screen.getByText("a 2-D PSD")).toBeVisible();
    expect(screen.getByRole("img", { name: "2-D PSD map preview" })).toHaveAttribute(
      "src",
      "/api/image/psd/render?max_dim=512",
    );
    expect(screen.getByRole("status")).toHaveTextContent("created in Library");

    fireEvent.change(screen.getByLabelText(/background removal/i), { target: { value: "none" } });
    expect(screen.getByText("Settings changed")).toBeVisible();
    expect(screen.getByRole("button", { name: "Raw source in 3-D" })).toHaveAttribute(
      "title",
      expect.stringContaining("original height map"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Step height" }));
    expect(useViewer.getState().tools.some((tool) => tool.kind === "afmstep")).toBe(true);
  });

  it("ignores a map that finishes after the source changes", async () => {
    let resolve!: (meta: ImageMeta) => void;
    vi.mocked(afmMap).mockReturnValue(new Promise((done) => { resolve = done; }));
    useViewer.getState().ingest([image("a"), image("b")]);
    useViewer.getState().setActive("a");
    render(<AfmSurfaceWorkshop />);

    fireEvent.click(screen.getByRole("button", { name: "Create ACF" }));
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve({ ...image("acf"), name: "old ACF" }));

    expect(useViewer.getState().activeId).toBe("b");
    expect(useViewer.getState().images.acf).toBeUndefined();
  });

  it("groups complete results and shows one selected plot at a time", async () => {
    const result = surface(3);
    result.psd = { frequency: [1, 2], power: [3, 4] };
    result.height_hist = { height: [1, 2], percent: [3, 4] };
    result.slope_hist = { angle: [1, 2], percent: [3, 4] };
    vi.mocked(afmSurface).mockResolvedValue(result);
    useViewer.getState().ingest([image("a")]);
    useViewer.getState().setActive("a");
    render(<AfmSurfaceWorkshop />);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Analyze" })));

    expect(screen.getAllByText("Height").length).toBeGreaterThan(0);
    expect(screen.getByText("7 parameters")).toBeVisible();
    expect(screen.getByText("7 parameters").closest("details")).toHaveAttribute("open");
    expect(screen.getByText("Sdr")).toBeInTheDocument();
    const hybridGroup = screen.getByText("2 parameters").closest("details");
    fireEvent.click(hybridGroup!.querySelector("summary")!);
    expect(hybridGroup).toHaveAttribute("open");
    expect(screen.getByRole("tab", { name: "Spectrum" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Radial power spectral density")).toBeVisible();
    expect(screen.queryByText("Height distribution")).toBeNull();

    fireEvent.click(screen.getByRole("tab", { name: "Heights" }));
    expect(screen.getByRole("tab", { name: "Heights" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Height distribution")).toBeVisible();
    expect(screen.queryByText("Radial power spectral density")).toBeNull();

    fireEvent.keyDown(screen.getByRole("tab", { name: "Heights" }), { key: "ArrowRight" });
    expect(screen.getByRole("tab", { name: "Slopes" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Slope distribution")).toBeVisible();

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Analyze" })));
    expect(screen.getByText("2 parameters").closest("details")).toHaveAttribute("open");
  });

  it("keeps old provenance visible but blocks export after settings change", async () => {
    vi.mocked(afmSurface).mockResolvedValue(surface(3));
    useViewer.getState().ingest([image("a")]);
    useViewer.setState({ savedRois: { a: [savedRoi] } });
    useViewer.getState().setActive("a");
    useWorkshop.getState().setAnalysisRegionChoice("a", "saved:r1");
    render(<AfmSurfaceWorkshop />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Analyze" }));
    });
    // choosing another region afterwards does not relabel the old result,
    // but makes it visibly stale and unexportable
    act(() => useWorkshop.getState().setAnalysisRegionChoice("a", "whole"));
    fireEvent.change(screen.getByLabelText(/background removal/i), { target: { value: "none" } });
    expect(screen.getByText("Terrace · plane levelling")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/out of date/i);
    expect(screen.getByRole("button", { name: "Update analysis" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Export JSON" })).toBeDisabled();
    expect(downloadJson).not.toHaveBeenCalled();
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
