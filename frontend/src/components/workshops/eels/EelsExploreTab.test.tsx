// EelsExploreTab receives its spectrum as a prop (EelsWorkshop owns the
// fetch), so these tests exercise the readout/marker wiring directly —
// no lib/api mock needed, just a plain uPlot stub (SpectrumPlot's own tests
// cover the drag gestures in detail).

import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { describe, expect, it, vi } from "vitest";

import type { EelsBackgroundResult, Spectrum } from "../../../lib/api";
import EelsExploreTab from "./EelsExploreTab";

vi.mock("uplot", () => ({
  default: class {
    over = document.createElement("div");
    bbox = { left: 0, top: 0, width: 320, height: 200 };
    scales = { x: {} };
    constructor(_options: unknown, _data: unknown, host: HTMLElement) {
      host.appendChild(document.createElement("canvas"));
      host.appendChild(this.over);
    }
    destroy() {}
    setSize() {}
    redraw() {}
    setScale() {}
    setSelect() {}
    posToVal(v: number) {
      return v;
    }
    valToPos(v: number) {
      return v;
    }
  },
}));

const SPEC: Spectrum = {
  energy: [100, 200, 300, 400, 500, 600],
  counts: [10, 12, 11, 40, 60, 30],
  units: "eV",
};

type Props = ComponentProps<typeof EelsExploreTab>;

function baseProps(overrides: Partial<Props> = {}): Props {
  const noop = () => {};
  return {
    activeId: "eels-1",
    spectrum: SPEC,
    fit: null,
    isCube: false,
    bgLo: "100",
    bgHi: "300",
    sigLo: "400",
    sigHi: "600",
    setBgLo: noop,
    setBgHi: noop,
    setSigLo: noop,
    setSigHi: noop,
    runFit: noop,
    runMap: noop,
    showEdges: false,
    setShowEdges: noop,
    elementFilter: "",
    setElementFilter: noop,
    region: null,
    setRegion: noop,
    captureMode: "none",
    onToggleLive: noop,
    specnavPixel: null,
    ...overrides,
  };
}

describe("EelsExploreTab", () => {
  it("shows a live net/gross/background readout for the current windows", () => {
    render(<EelsExploreTab {...baseProps()} />);
    // signal [400,600] sums counts 40+60+30 = 130
    expect(screen.getByText(/Net .* · gross 130/)).toBeVisible();
  });

  it("reports no channels when the signal window misses every point", () => {
    render(
      <EelsExploreTab {...baseProps({ sigLo: "10000", sigHi: "10001" })} />,
    );
    expect(
      screen.getByText("No channels in the signal window."),
    ).toBeVisible();
  });

  it("recomputes the readout when the signal window strings change", () => {
    const { rerender } = render(<EelsExploreTab {...baseProps()} />);
    expect(screen.getByText(/gross 130/)).toBeVisible();

    // narrow the signal window to the single 400 channel (gross 40)
    rerender(<EelsExploreTab {...baseProps({ sigLo: "400", sigHi: "400" })} />);
    expect(screen.getByText(/gross 40\b/)).toBeVisible();
  });

  it("notes a direct sum when no background window is set", () => {
    render(<EelsExploreTab {...baseProps({ bgLo: "", bgHi: "" })} />);
    expect(screen.getByText(/no background window/)).toBeVisible();
  });

  it("builds edge-onset markers without throwing once Edge IDs is on", () => {
    // Markers paint on the uPlot canvas (not observable via the DOM with
    // this stub); this exercises the KNOWN_EDGES filter/range/splitEdgeLabel
    // path (C-K at 284 eV falls inside [0, 1000]) and asserts the component
    // still renders cleanly with a live marker set.
    render(
      <EelsExploreTab
        {...baseProps({
          spectrum: { energy: [0, 1000], counts: [1, 1], units: "eV" },
          showEdges: true,
          elementFilter: "C",
        })}
      />,
    );
    expect(screen.getByText("Edge IDs")).toBeVisible();
  });

  it("shows the last Fit result's power-law exponent as a note", () => {
    const fit: EelsBackgroundResult = {
      energy: SPEC.energy,
      spectrum: SPEC.counts,
      background: SPEC.energy.map(() => 5),
      signal: SPEC.energy.map(() => 5),
      params: { A: 1, r: 2.5 },
    };
    render(<EelsExploreTab {...baseProps({ fit })} />);
    expect(screen.getByText(/r = 2.500/)).toBeVisible();
  });
});
