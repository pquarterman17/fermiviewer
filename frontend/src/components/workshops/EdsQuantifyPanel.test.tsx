import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  CompositionProfileResult,
  EdsQuantResult,
  ImageMeta,
} from "../../lib/api";
import { BAND_LEGEND_ROW_CLASS } from "../../lib/charts/sigmaBand";
import { useViewer } from "../../store/viewer";

// Mirrors EelsResults.test.tsx's uPlot mock: records what CompProfilePlot
// passes to `new uPlot(...)` without touching jsdom's unimplemented canvas
// 2D context. Lives in vi.hoisted() because vi.mock's factory is lifted
// above every top-level binding in the file.
const mock = vi.hoisted(() => {
  const state = {
    options: {} as Record<string, unknown>,
    data: undefined as unknown,
  };
  class Plot {
    constructor(
      options: Record<string, unknown>,
      data: unknown,
      host: HTMLElement,
    ) {
      state.options = options;
      state.data = data;
      host.appendChild(document.createElement("canvas"));
    }
    destroy() {}
    setSize() {}
  }
  return { state, Plot };
});
vi.mock("uplot", () => ({ default: mock.Plot }));
vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    analyzeCompositionProfile: vi.fn(),
    edsAutoAssign: vi.fn(),
    edsQuantify: vi.fn(),
  };
});

import {
  analyzeCompositionProfile,
  edsAutoAssign,
  edsQuantify,
} from "../../lib/api";
import { CompProfilePlot } from "./EdsQuantifyPanel";
import EdsQuantifyPanel from "./EdsQuantifyPanel";

const RESULT: CompositionProfileResult = {
  distance: [0, 1, 2, 3],
  atomic_pct: [
    [90, 60, 30, 10], // Cu
    [10, 40, 70, 90], // Ni
  ],
  atomic_percent_error: [
    [1, 1.5, 2, 1],
    [0.5, 1, 1.5, 0.8],
  ],
  elements: ["Cu", "Ni"],
  unit: "nm",
};

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

afterEach(() => {
  vi.clearAllMocks();
  useViewer.setState({
    images: {},
    order: [],
    activeId: null,
    selected: [],
    measures: {},
  });
});

function image(id: string, kind: ImageMeta["kind"] = "spectrum_image"): ImageMeta {
  return {
    id,
    name: `${id}.bcf`,
    kind,
    shape: [16, 16, 64],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "counts",
    n_channels: 64,
    energy_first: 0,
    energy_last: 10,
    energy_units: "keV",
    stage_tilt_deg: null,
    meta: {},
  };
}

function quantResult(): EdsQuantResult {
  return {
    elements: ["Fe"],
    lines: ["K"],
    mean_atomic_pct: [100],
    mean_weight_pct: [100],
    mean_atomic_pct_error: [1],
    mean_weight_pct_error: [1],
    k_factors: [1],
    maps: [image("fe-map", "image")],
  };
}

type Series = { label?: string; class?: string; show?: boolean };

describe("CompProfilePlot", () => {
  it("keeps the main element lines at series[1..n], matching atomic_pct's own order", () => {
    render(<CompProfilePlot r={RESULT} />);
    const series = mock.state.options.series as Series[];
    expect(series[0]).toEqual({ label: "d (nm)" });
    expect(series[1].label).toBe("Cu");
    expect(series[2].label).toBe("Ni");
    // legend-click → series index mapping for an element is `elements`
    // order + 1 (x is index 0) -- this must survive appending bands after.
    expect(RESULT.elements.indexOf("Cu")).toBe(0);
    expect(RESULT.elements.indexOf("Ni")).toBe(1);
  });

  it("appends one hi/lo band-boundary pair per element AFTER the main lines", () => {
    render(<CompProfilePlot r={RESULT} />);
    const series = mock.state.options.series as Series[];
    // x + 2 main lines + 2 elements * (hi, lo) = 7 series total
    expect(series).toHaveLength(7);
    for (const s of series.slice(3)) {
      expect(s.class).toBe(BAND_LEGEND_ROW_CLASS);
      expect(s.show).toBe(true); // bands only fill when both edges are shown
    }
  });

  it("wires bands[] to the exact series indices of each element's hi/lo pair", () => {
    render(<CompProfilePlot r={RESULT} />);
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands.map((b) => b.series)).toEqual([
      [3, 4], // Cu: hi=3, lo=4 (after x@0, Cu@1, Ni@2)
      [5, 6], // Ni: hi=5, lo=6
    ]);
  });

  it("hi/lo data rows are y ± sigma for the matching element", () => {
    render(<CompProfilePlot r={RESULT} />);
    const data = mock.state.data as number[][];
    // data layout: [distance, Cu, Ni, CuHi, CuLo, NiHi, NiLo]
    expect(data[3]).toEqual([91, 61.5, 32, 11]); // Cu + sigma
    expect(data[4]).toEqual([89, 58.5, 28, 9]); // Cu - sigma
    expect(data[5]).toEqual([10.5, 41, 71.5, 90.8]); // Ni + sigma
    expect(data[6]).toEqual([9.5, 39, 68.5, 89.2]); // Ni - sigma
  });

  it("renders no band series when the response carries no sigma (older/degraded response)", () => {
    const noSigma: CompositionProfileResult = {
      ...RESULT,
      atomic_percent_error: undefined,
    };
    render(<CompProfilePlot r={noSigma} />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(3); // x + Cu + Ni, no band pairs
    expect(mock.state.options.bands).toEqual([]);
  });
});

describe("EdsQuantifyPanel request ownership", () => {
  it("drops a quantify response after the active cube changes", async () => {
    let resolve!: (value: EdsQuantResult) => void;
    vi.mocked(edsQuantify).mockReturnValue(new Promise((r) => { resolve = r; }));
    useViewer.getState().ingest([image("a"), image("b")]);
    useViewer.getState().setActive("a");
    const onResult = vi.fn();
    render(
      <EdsQuantifyPanel elements="Fe" onElements={vi.fn()} onResult={onResult} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Quantify" }));
    const signal = vi.mocked(edsQuantify).mock.calls[0]![2]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve(quantResult()));

    expect(signal.aborted).toBe(true);
    expect(onResult).not.toHaveBeenCalledWith(expect.objectContaining({ elements: ["Fe"] }));
    expect(useViewer.getState().images).not.toHaveProperty("fe-map");
    expect(screen.queryByText("100.00 ± 1.00")).toBeNull();
  });

  it("drops auto-assigned elements after the active cube changes", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof edsAutoAssign>>) => void;
    vi.mocked(edsAutoAssign).mockReturnValue(new Promise((r) => { resolve = r; }));
    useViewer.getState().ingest([image("a"), image("b")]);
    useViewer.getState().setActive("a");
    const onElements = vi.fn();
    render(
      <EdsQuantifyPanel elements="" onElements={onElements} onResult={vi.fn()} />,
    );

    fireEvent.click(screen.getByRole("button", { name: "Auto-assign" }));
    const signal = vi.mocked(edsAutoAssign).mock.calls[0]![1]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () =>
      resolve({
        peaks_kev: [6.4],
        assignments: [{
          peak_kev: 6.4,
          candidates: [{
            symbol: "Fe", line: "K", energy_kev: 6.4, delta_kev: 0,
          }],
        }],
      }),
    );

    expect(signal.aborted).toBe(true);
    expect(onElements).not.toHaveBeenCalled();
  });

  it("drops a composition profile after the source cube changes", async () => {
    vi.mocked(edsQuantify).mockResolvedValue(quantResult());
    let resolve!: (value: CompositionProfileResult) => void;
    vi.mocked(analyzeCompositionProfile).mockReturnValue(
      new Promise((r) => { resolve = r; }),
    );
    useViewer.getState().ingest([image("a"), image("b")]);
    useViewer.setState({
      activeId: "a",
      measures: {
        a: [{
          id: "line",
          kind: "distance",
          pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
        }],
      },
    });
    render(
      <EdsQuantifyPanel elements="Fe" onElements={vi.fn()} onResult={vi.fn()} />,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Quantify" }));
    });
    fireEvent.click(screen.getByRole("button", { name: "Comp Profile" }));
    const signal = vi.mocked(analyzeCompositionProfile).mock.calls[0]![5]!.signal!;
    act(() => useViewer.getState().setActive("b"));
    await act(async () => resolve(RESULT));

    expect(signal.aborted).toBe(true);
    expect(screen.queryByLabelText("Composition profile")).toBeNull();
  });
});
