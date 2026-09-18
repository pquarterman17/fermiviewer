import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BAND_LEGEND_ROW_CLASS } from "../../lib/charts/sigmaBand";
import { useStageInfo } from "../../store/stage";

// Mirrors EelsFitOverlayPlot.test.tsx's uPlot mock: records what DockPlot
// passes to `new uPlot(...)` without touching jsdom's unimplemented canvas
// 2D context.
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

import DockPlot from "./DockPlot";

type Series = { label?: string; class?: string; stroke?: string };

beforeEach(() => {
  mock.state.options = {};
  mock.state.data = undefined;
});

afterEach(() => {
  useStageInfo.getState().setProfile(null);
});

describe("DockPlot", () => {
  it("renders nothing when there is no active profile", () => {
    const { container } = render(<DockPlot />);
    expect(container).toBeEmptyDOMElement();
  });

  it("draws just the distance/intensity line when intensity_sigma is absent (old server / cached results)", () => {
    useStageInfo.getState().setProfile({
      measureId: "__radial__",
      dist: [0, 1, 2],
      intensity: [10, 20, 30],
      length: 2,
      unit: "px",
      reduce: "mean",
    });
    render(<DockPlot />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(2);
    expect(mock.state.options.bands).toEqual([]);
    expect(series.some((s) => s.class === BAND_LEGEND_ROW_CLASS)).toBe(false);
  });

  it("shades intensity ± sem when intensity_sigma is present", () => {
    useStageInfo.getState().setProfile({
      measureId: "__radial__",
      dist: [0, 1, 2],
      intensity: [10, 20, 30],
      intensity_sigma: [1, 2, null],
      length: 2,
      unit: "px",
      reduce: "mean",
    });
    render(<DockPlot />);
    const series = mock.state.options.series as Series[];
    expect(series).toHaveLength(4); // x, I, hi, lo
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
    const [hi, lo] = bands[0].series;
    expect(hi).toBe(2);
    expect(lo).toBe(3);
    expect(series[hi].class).toBe(BAND_LEGEND_ROW_CLASS);
    expect(series[lo].class).toBe(BAND_LEGEND_ROW_CLASS);

    const data = mock.state.data as (number | null)[][];
    expect(data[hi]).toEqual([11, 22, null]);
    expect(data[lo]).toEqual([9, 18, null]);
  });

  it("renders a band for a line-profile payload the same way as radial (same field)", () => {
    useStageInfo.getState().setProfile({
      measureId: "m1",
      dist: [0, 1],
      intensity: [5, 6],
      intensity_sigma: [0.5, 0.5],
      length: 1,
      unit: "nm",
      reduce: "mean",
    });
    render(<DockPlot />);
    const bands = mock.state.options.bands as { series: [number, number] }[];
    expect(bands).toHaveLength(1);
  });
  // ── span measurement + edge fit ────────────────────────────────────

  const withProfile = () => {
    useStageInfo.getState().setProfile({
      measureId: "m1",
      dist: [0, 1, 2, 3, 4, 5, 6, 7],
      intensity: [0, 0, 1, 4, 7, 9, 10, 10],
      length: 7,
      unit: "nm",
      reduce: "mean",
    });
    return render(<DockPlot />);
  };

  it("leaves drag zooming alone until measuring is turned on", () => {
    withProfile();
    // the default cursor must not claim the drag: turning measurement on by
    // default would silently take zoom away from every existing user
    expect(mock.state.options.cursor).toEqual({ y: false });
    expect(mock.state.options.hooks).toEqual({});
  });

  it("keeps the selection instead of zooming to it while measuring", () => {
    withProfile();
    fireEvent.click(screen.getByRole("button", { name: /Measure span/ }));
    const cursor = mock.state.options.cursor as {
      drag?: { x?: boolean; setScale?: boolean };
    };
    expect(cursor.drag?.x).toBe(true);
    // setScale false is the whole trick: same gesture, selection retained
    expect(cursor.drag?.setScale).toBe(false);
    expect(screen.getByText(/Drag across the plot/)).toBeInTheDocument();
  });

  it("reports the span's length and step once a selection is made", () => {
    withProfile();
    fireEvent.click(screen.getByRole("button", { name: /Measure span/ }));
    const hooks = mock.state.options.hooks as {
      setSelect: ((u: unknown) => void)[];
    };
    // act(): uPlot calls this hook from its own event handling, outside
    // React, so the state update it triggers must be flushed explicitly
    act(() => {
      hooks.setSelect[0]({
        select: { left: 0, width: 50 },
        posToVal: (px: number) => (px === 0 ? 1 : 6),
      });
    });
    // 1 -> 6 nm spans 5 nm, over samples rising 0 -> 10. Read the bar's
    // whole text: the numbers are interpolated, so each reading is split
    // across text nodes and an exact-string matcher would not see it.
    const bar = document.querySelector(".fvd-dock-measure")!;
    expect(bar.textContent).toContain("Δ 5 nm");
    expect(bar.textContent).toContain("step 10");
    expect(screen.getByRole("button", { name: "Fit edge" })).toBeInTheDocument();
  });

  it("ignores a zero-width selection, which is a click and not a span", () => {
    withProfile();
    fireEvent.click(screen.getByRole("button", { name: /Measure span/ }));
    const hooks = mock.state.options.hooks as {
      setSelect: ((u: unknown) => void)[];
    };
    act(() => {
      hooks.setSelect[0]({
        select: { left: 10, width: 0 },
        posToVal: () => 3,
      });
    });
    expect(screen.getByText(/Drag across the plot/)).toBeInTheDocument();
  });
});
