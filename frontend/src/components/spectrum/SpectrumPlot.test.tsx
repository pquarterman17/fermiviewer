import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import type { Spectrum } from "../../lib/api";

interface Hooks {
  setSelect?: ((plot: MockPlot) => void)[];
  setScale?: ((plot: MockPlot, key: string) => void)[];
}

interface MockPlot {
  bbox: { left: number; top: number; width: number; height: number };
  data: unknown;
  over: HTMLDivElement;
  select: { left: number; top: number; width: number; height: number };
  cursor: { drag: { setScale: boolean } };
  scales: { x: { min?: number; max?: number } };
}

// The mock mirrors the parts of uPlot this component actually drives: the
// `.u-over` element that receives every pointer event inside the plot area,
// the mutable `cursor.drag.setScale` flag, and the select rectangle the
// setSelect hook reads. It lives in vi.hoisted() because vi.mock's factory is
// lifted above every top-level binding in the file.
const mock = vi.hoisted(() => {
  const state = {
    options: {} as Record<string, unknown>,
    instance: null as unknown,
  };
  const setScale = vi.fn();
  const setSelect = vi.fn();

  class Plot {
    bbox = { left: 0, top: 0, width: 320, height: 200 };
    data: unknown;
    over: HTMLDivElement;
    select = { left: 0, top: 0, width: 0, height: 0 };
    cursor = { drag: { setScale: true } };
    scales: { x: { min?: number; max?: number } } = { x: {} };

    constructor(
      options: Record<string, unknown>,
      data: unknown,
      host: HTMLElement,
    ) {
      state.options = options;
      this.data = data;
      host.appendChild(document.createElement("canvas"));
      this.over = document.createElement("div");
      host.appendChild(this.over);
      state.instance = this;
    }

    destroy() {}
    posToVal(value: number) {
      return value;
    }
    valToPos(value: number) {
      return value;
    }
    setSize() {}
    redraw() {}
    setScale = setScale;
    setSelect = setSelect;
  }

  return { state, setScale, setSelect, Plot };
});

vi.mock("uplot", () => ({ default: mock.Plot }));

const plot = () => mock.state.instance as MockPlot;
const hooks = () => (mock.state.options.hooks ?? {}) as Hooks;

import SpectrumPlot from "./SpectrumPlot";

const WIDE: Spectrum = {
  energy: [0, 5, 10, 15, 20],
  counts: [1, 2, 30, 2, 1],
  units: "keV",
};

beforeAll(() => {
  class ResizeObserverStub {
    observe() {}
    disconnect() {}
  }
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    value: ResizeObserverStub,
  });
});

beforeEach(() => {
  mock.setScale.mockClear();
  mock.setSelect.mockClear();
});

describe("EdsSpectrumPlot", () => {
  it("reserves a readable count gutter and uses compact y ticks", () => {
    render(
      <SpectrumPlot
        spec={{ energy: [0.49, 0.54], counts: [125_000, 1_250_000], units: "keV" }}
        label="Sum spectrum"
        eLo={0.5}
        eHi={0.6}
        onDragWindow={() => {}}
      />,
    );

    type Axis = {
      size?: number;
      values?: (plot: unknown, ticks: number[]) => string[];
    };
    const axes = mock.state.options.axes as Axis[];
    expect(axes[1].size).toBe(64);
    expect(axes[1].values?.(null, [0, 125_000, 1_250_000])).toEqual([
      "0",
      "125k",
      "1.25M",
    ]);
  });

  it("opens plot actions on right-click and resets the spectrum view", () => {
    render(
      <SpectrumPlot
        spec={{ energy: [0.49, 0.54], counts: [1, 2], units: "keV" }}
        label="Sum spectrum"
        eLo={0.5}
        eHi={0.6}
        onDragWindow={() => {}}
      />,
    );

    fireEvent.contextMenu(screen.getByLabelText("Sum spectrum plot"), {
      clientX: 120,
      clientY: 80,
    });
    expect(
      screen.getByRole("menu", { name: "Sum spectrum plot actions" }),
    ).toBeVisible();
    fireEvent.click(screen.getByRole("menuitem", { name: "Reset view" }));
    expect(mock.setScale).toHaveBeenCalledWith("x", { min: 0.49, max: 0.54 });
  });

  it("shift+drag sets the energy window and suppresses the native zoom", () => {
    const onDragWindow = vi.fn();
    render(
      <SpectrumPlot
        spec={WIDE}
        label="Sum spectrum"
        eLo={9}
        eHi={11}
        onDragWindow={onDragWindow}
      />,
    );

    fireEvent.mouseDown(plot().over, { shiftKey: true });
    // uPlot checks cursor.drag.setScale at mouseup; leaving it false is what
    // turns its zoom-drag into a window-drag.
    expect(plot().cursor.drag.setScale).toBe(false);

    plot().select = { left: 30, top: 0, width: 40, height: 200 };
    hooks().setSelect?.[0](plot());

    expect(onDragWindow).toHaveBeenCalledWith(30, 70);
    // and the selection rectangle is cleared without re-firing hooks
    expect(mock.setSelect).toHaveBeenCalledWith(
      { left: 0, top: 0, width: 0, height: 0 },
      false,
    );
  });

  it("leaves a plain drag to uPlot's zoom and never moves the window", () => {
    const onDragWindow = vi.fn();
    render(
      <SpectrumPlot
        spec={WIDE}
        label="Sum spectrum"
        eLo={9}
        eHi={11}
        onDragWindow={onDragWindow}
      />,
    );

    fireEvent.mouseDown(plot().over, { shiftKey: false });
    expect(plot().cursor.drag.setScale).toBe(true);

    plot().select = { left: 30, top: 0, width: 40, height: 200 };
    hooks().setSelect?.[0](plot());

    expect(onDragWindow).not.toHaveBeenCalled();
    expect(mock.setSelect).not.toHaveBeenCalled();
  });

  it("wheels a zoom about the energy under the cursor", () => {
    const onXRangeChange = vi.fn<(next: unknown) => void>();
    render(
      <SpectrumPlot
        spec={WIDE}
        label="Sum spectrum"
        eLo={9}
        eHi={11}
        onDragWindow={() => {}}
        onXRangeChange={onXRangeChange}
      />,
    );
    onXRangeChange.mockClear();

    fireEvent.wheel(plot().over, { deltaY: -100, clientX: 10 });
    // the updater form is what makes successive wheel steps compose
    const update = onXRangeChange.mock.calls[0][0] as (
      prev: [number, number] | null,
    ) => [number, number] | null;
    // full range [0, 20] scaled by 1/1.25 about 10 → [2, 18]
    expect(update(null)).toEqual([2, 18]);
    // and a second step composes from that, rather than from the full range
    const second = update([2, 18])!;
    expect(second[0]).toBeCloseTo(3.6, 10);
    expect(second[1]).toBeCloseTo(16.4, 10);
  });

  it("reports a full-width scale as null so the axis returns to auto", () => {
    const onXRangeChange = vi.fn();
    render(
      <SpectrumPlot
        spec={WIDE}
        label="Sum spectrum"
        eLo={9}
        eHi={11}
        onDragWindow={() => {}}
        onXRangeChange={onXRangeChange}
      />,
    );
    onXRangeChange.mockClear();

    plot().scales.x = { min: 4, max: 12 };
    hooks().setScale?.[0](plot(), "x");
    expect(onXRangeChange).toHaveBeenLastCalledWith([4, 12]);

    plot().scales.x = { min: 0, max: 20 };
    hooks().setScale?.[0](plot(), "x");
    expect(onXRangeChange).toHaveBeenLastCalledWith(null);
  });
});
