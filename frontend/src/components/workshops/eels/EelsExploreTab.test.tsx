// EelsExploreTab receives its spectrum as a prop (EelsWorkshop owns the
// fetch), so these tests exercise the readout/marker/store wiring directly.
//
// SpectrumPlot itself is mocked rather than the underlying uPlot: (1) it
// lets these tests drive onDragWindowsLive/onDragWindowsCommit directly,
// which is what the store-commit tests below need and no synthetic pointer
// gesture on a stubbed uPlot could exercise honestly; (2) Wave 2 of this
// campaign owns components/spectrum/* and may be mid-refactor of its
// internals — this test only needs SpectrumPlot's EELS-facing prop
// contract (onDragWindowsLive/onDragWindowsCommit/background/overlays),
// which is guaranteed stable, so stubbing the component insulates these
// tests from anything else changing underneath it. SpectrumPlot's own
// gesture tests remain the place drag mechanics are covered.

import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState, type ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { EelsBackgroundResult, Spectrum } from "../../../lib/api";
import { eelsSpecies } from "../../../lib/spectrum/species";
import { useSpecies } from "../../../store/species";
import EelsExploreTab from "./EelsExploreTab";

const spectrumPlotProps = vi.hoisted(() => ({
  current: null as null | Record<string, unknown>,
}));

vi.mock("../../spectrum/SpectrumPlot", () => ({
  default: (props: Record<string, unknown>) => {
    spectrumPlotProps.current = props;
    return <div data-testid="spectrum-plot-stub" />;
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

afterEach(() => {
  spectrumPlotProps.current = null;
  useSpecies.setState({ byImage: {}, selectedByImage: {}, edsSettingsByImage: {} });
});

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
    // Markers are handed to the (stubbed) SpectrumPlot as a prop, not
    // observable via the DOM here; this exercises the KNOWN_EDGES
    // filter/range/splitEdgeLabel path (C-K at 284 eV falls inside
    // [0, 1000]) and asserts the component still renders cleanly with a
    // live marker set.
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

/** EelsWorkshop owns bgLo/bgHi/sigLo/sigHi as real `useState`, not the
 *  fire-and-forget spies `baseProps()` defaults to — the store-backed tests
 *  below need the fields to actually re-render when the sync effect calls
 *  the setters, so this stands in for that parent. */
function Harness(overrides: Partial<Props> & { activeId: string }) {
  const initial = baseProps(overrides);
  const [bgLo, setBgLo] = useState(initial.bgLo);
  const [bgHi, setBgHi] = useState(initial.bgHi);
  const [sigLo, setSigLo] = useState(initial.sigLo);
  const [sigHi, setSigHi] = useState(initial.sigHi);
  return (
    <EelsExploreTab
      {...initial}
      bgLo={bgLo}
      bgHi={bgHi}
      sigLo={sigLo}
      sigHi={sigHi}
      setBgLo={setBgLo}
      setBgHi={setBgHi}
      setSigLo={setSigLo}
      setSigHi={setSigHi}
    />
  );
}

describe("EelsExploreTab store-backed windows", () => {
  it("auto-selects the first visible species and shows its windows in the fields", () => {
    const sp = eelsSpecies("Fe", "L23", 400, {
      windows: {
        signal: { lo: 400, hi: 600 },
        background: { lo: 350, hi: 390 },
      },
    });
    useSpecies.getState().setSpecies("eels-1", [sp]);

    render(<Harness activeId="eels-1" />);

    expect(screen.getByDisplayValue("400")).toBeInTheDocument();
    expect(screen.getByDisplayValue("600")).toBeInTheDocument();
    expect(screen.getByDisplayValue("350")).toBeInTheDocument();
    expect(screen.getByDisplayValue("390")).toBeInTheDocument();
    expect(useSpecies.getState().selectedByImage["eels-1"]).toBe(sp.id);
  });

  it("switching species (SpeciesChips, mirroring a Maps row click) swaps the edited windows", () => {
    const fe = eelsSpecies("Fe", "L23", 400, {
      windows: { signal: { lo: 400, hi: 600 }, background: { lo: 350, hi: 390 } },
    });
    const o = eelsSpecies("O", "K", 150, {
      windows: { signal: { lo: 150, hi: 250 }, background: { lo: 100, hi: 140 } },
    });
    useSpecies.getState().setSpecies("eels-1", [fe, o]);

    render(<Harness activeId="eels-1" />);
    expect(screen.getByDisplayValue("400")).toBeInTheDocument(); // Fe auto-selected

    fireEvent.click(screen.getByRole("option", { name: "O" }));

    expect(screen.getByDisplayValue("150")).toBeInTheDocument();
    expect(screen.getByDisplayValue("250")).toBeInTheDocument();
    expect(screen.getByDisplayValue("100")).toBeInTheDocument();
    expect(screen.getByDisplayValue("140")).toBeInTheDocument();
  });

  it("commits a preset click to the selected species in the store", () => {
    const sp = eelsSpecies("Fe", "L23", 400, { widthEv: 50 });
    useSpecies.getState().setSpecies("eels-1", [sp]);

    render(<Harness activeId="eels-1" />);
    fireEvent.click(screen.getByRole("button", { name: "wide" }));

    // EELS_PRESET_WIDTH_EV.wide = 100 eV past the 400 eV onset.
    const stored = useSpecies.getState().byImage["eels-1"][0];
    expect(stored.windows.signal).toEqual({ lo: 400, hi: 500 });
  });

  it("commits a typed window edit to the store on blur, not on every keystroke", () => {
    const sp = eelsSpecies("Fe", "L23", 400, {
      windows: { signal: { lo: 400, hi: 600 }, background: { lo: 350, hi: 390 } },
    });
    useSpecies.getState().setSpecies("eels-1", [sp]);

    render(<Harness activeId="eels-1" />);
    const sigHiInput = screen.getByDisplayValue("600");
    fireEvent.change(sigHiInput, { target: { value: "620" } });
    expect(useSpecies.getState().byImage["eels-1"][0].windows.signal.hi).toBe(600);

    fireEvent.blur(sigHiInput);
    expect(useSpecies.getState().byImage["eels-1"][0].windows.signal.hi).toBe(620);
  });

  // Mutation-verified: commenting out the `setWindow` call inside
  // `commitWindows` (leaving `handleWindowsChange` in place) turns the
  // second assertion red while the first stays green, confirming this test
  // actually distinguishes "local" from "committed" rather than passing
  // vacuously. Restored after confirming the failure.
  it("keeps a live drag local — the store commits only when the drag is released", () => {
    const sp = eelsSpecies("Fe", "L23", 400, {
      windows: { signal: { lo: 400, hi: 600 }, background: { lo: 350, hi: 390 } },
    });
    useSpecies.getState().setSpecies("eels-1", [sp]);

    render(<Harness activeId="eels-1" />);
    expect(screen.getByDisplayValue("600")).toBeInTheDocument();

    act(() => {
      (spectrumPlotProps.current!.onDragWindowsLive as (w: unknown) => void)({
        signal: { lo: 400, hi: 650 },
      });
    });
    expect(screen.getByDisplayValue("650")).toBeInTheDocument();
    expect(useSpecies.getState().byImage["eels-1"][0].windows.signal).toEqual({
      lo: 400,
      hi: 600,
    });

    act(() => {
      (spectrumPlotProps.current!.onDragWindowsCommit as (w: unknown) => void)({
        signal: { lo: 400, hi: 650 },
      });
    });
    expect(useSpecies.getState().byImage["eels-1"][0].windows.signal).toEqual({
      lo: 400,
      hi: 650,
    });
  });

  it("never crashes with an empty species list, and points at Maps instead", () => {
    render(<Harness activeId="eels-1" />);
    expect(
      screen.getByText(
        "No species yet — identify or add elements from the Maps tab.",
      ),
    ).toBeVisible();
  });
});
