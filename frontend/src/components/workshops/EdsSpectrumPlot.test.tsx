import { render } from "@testing-library/react";
import { beforeAll, describe, expect, it, vi } from "vitest";

let capturedOptions: Record<string, unknown> = {};

vi.mock("uplot", () => ({
  default: class {
    bbox = { left: 0, top: 0, width: 320, height: 200 };

    constructor(
      options: Record<string, unknown>,
      _data: unknown,
      host: HTMLElement,
    ) {
      capturedOptions = options;
      host.appendChild(document.createElement("canvas"));
    }

    destroy() {}
    posToVal(value: number) {
      return value;
    }
    setSize() {}
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
});
