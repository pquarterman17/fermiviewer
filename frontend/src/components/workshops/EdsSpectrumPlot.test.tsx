import { fireEvent, render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

let capturedOptions: Record<string, unknown> = {};
const setScale = vi.fn();

vi.mock("uplot", () => ({
  default: class {
    bbox = { left: 0, top: 0, width: 320, height: 200 };
    data: unknown;

    constructor(
      options: Record<string, unknown>,
      _data: unknown,
      host: HTMLElement,
    ) {
      capturedOptions = options;
      this.data = _data;
      host.appendChild(document.createElement("canvas"));
    }

    destroy() {}
    posToVal(value: number) {
      return value;
    }
    setSize() {}
    setScale = setScale;
  },
}));

import SpectrumPlot from "./EdsSpectrumPlot";

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
    const axes = capturedOptions.axes as Axis[];
    expect(axes[1].size).toBe(64);
    expect(axes[1].values?.(null, [0, 125_000, 1_250_000])).toEqual([
      "0",
      "125k",
      "1.25M",
    ]);
  });

  it("opens plot actions on right-click and resets the spectrum view", () => {
    setScale.mockClear();
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
    expect(setScale).toHaveBeenCalledWith("x", { min: 0.49, max: 0.54 });
  });
});
