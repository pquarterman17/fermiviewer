import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { EdsElementMapResult, ImageMeta, Spectrum } from "../../lib/api";
import { edsSpecies } from "../../lib/spectrum/species";
import { useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";

// SpectrumPlot's own drag/nudge/wheel mechanics are covered by
// SpectrumPlot.test.tsx; here it is a thin stub exposing the two window
// callbacks as buttons, so this file tests EdsSpectrumImage's OWN wiring
// (species → window → store) without re-simulating uPlot pixel math.
vi.mock("../spectrum/SpectrumPlot", () => ({
  default: (props: {
    eLo: number;
    eHi: number;
    onDragWindowsLive?: (w: { signal: { lo: number; hi: number } }) => void;
    onDragWindowsCommit?: (w: { signal: { lo: number; hi: number } }) => void;
  }) => (
    <div data-testid="spectrum-plot">
      <span data-testid="plot-window">
        {props.eLo.toFixed(4)}-{props.eHi.toFixed(4)}
      </span>
      <button
        onClick={() =>
          props.onDragWindowsLive?.({
            signal: { lo: props.eLo - 0.01, hi: props.eHi + 0.01 },
          })
        }
      >
        live-drag
      </button>
      <button
        onClick={() =>
          props.onDragWindowsCommit?.({
            signal: { lo: props.eLo - 0.01, hi: props.eHi + 0.01 },
          })
        }
      >
        commit-drag
      </button>
    </div>
  ),
}));

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    fetchSpectrum: vi.fn(),
    edsElementMap: vi.fn(),
    edsAutoAssign: vi.fn(),
    edsLines: vi.fn(),
  };
});

import { edsAutoAssign, edsElementMap, edsLines, fetchSpectrum } from "../../lib/api";
import EdsSpectrumImage from "./EdsSpectrumImage";

const SPECTRUM: Spectrum = {
  // 0–7.9 keV: covers both Si Kα (~1.74) and Fe Kα (~6.404) windows with
  // margin, so integrateWindow never returns null (no channels) for either.
  energy: Array.from({ length: 80 }, (_, i) => i * 0.1),
  counts: Array.from({ length: 80 }, () => 5),
  units: "keV",
};

const MAP_RESULT: EdsElementMapResult = {
  map: [[1]],
  shape: [1, 1],
  e_lo: 1,
  e_hi: 2,
  bg: "linear",
  total_counts: 10,
  map_meta: null,
};

function cube(overrides: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id: "cube",
    name: "cube.dm4",
    kind: "spectrum_image",
    shape: [4, 4, 128],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "",
    n_channels: 128,
    energy_first: 0,
    energy_last: 6,
    energy_units: "keV",
    stage_tilt_deg: null,
    meta: {},
    ...overrides,
  } as ImageMeta;
}

function openCube(meta: ImageMeta = cube()) {
  useViewer.setState({
    images: { [meta.id]: meta },
    order: [meta.id],
    activeId: meta.id,
  });
  return meta;
}

beforeEach(() => {
  vi.mocked(fetchSpectrum).mockResolvedValue(SPECTRUM);
  vi.mocked(edsElementMap).mockResolvedValue(MAP_RESULT);
  vi.mocked(edsAutoAssign).mockResolvedValue({ peaks_kev: [], assignments: [] });
  vi.mocked(edsLines).mockResolvedValue([]);
});

afterEach(() => {
  vi.clearAllMocks();
  useSpecies.setState({ byImage: {}, selectedByImage: {}, edsSettingsByImage: {} });
  useViewer.setState({ images: {}, order: [], activeId: null });
});

describe("EdsSpectrumImage", () => {
  it("shows a quiet empty state pointing at Maps when the image has no species", async () => {
    openCube();
    render(<EdsSpectrumImage />);
    expect(
      await screen.findByText(/No species yet — identify or add them in the Maps tab/),
    ).toBeVisible();
    expect(
      screen.getByText(/No species yet — add elements in the Maps tab/),
    ).toBeVisible();
    // the window-tuning surfaces are gone with nothing selected...
    expect(screen.queryByRole("checkbox", { name: /Lock to line/ })).toBeNull();
    expect(screen.queryByRole("button", { name: "wide" })).toBeNull();
    // ...but the integration readout stays mounted (regions restore through
    // it even with nothing selected) and quietly reports there is nothing.
    expect(
      screen.getByRole("region", { name: "Spectrum integration" }),
    ).toBeVisible();
    expect(screen.getByText(/No channels in the current energy window/)).toBeVisible();
    expect(screen.getByRole("button", { name: "+ Add region" })).toBeDisabled();
  });

  it("auto-selects the first visible species when the image opens with none selected", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);

    render(<EdsSpectrumImage />);

    expect(await screen.findByRole("option", { name: "Fe" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(useSpecies.getState().selectedByImage[meta.id]).toBe(fe.id);
    // window controls now show — a species is selected
    expect(screen.getByRole("checkbox", { name: /Lock to line/ })).toBeVisible();
  });

  it("clicking a chip selects that species and its window replaces the display", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    const si = edsSpecies("Si", "K", 1.74);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().addSpecies(meta.id, si);
    useSpecies.getState().selectSpecies(meta.id, fe.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot");

    fireEvent.click(screen.getByRole("option", { name: "Si" }));

    expect(useSpecies.getState().selectedByImage[meta.id]).toBe(si.id);
    const { lo, hi } = si.windows.signal;
    expect(screen.getByTestId("plot-window")).toHaveTextContent(
      `${lo.toFixed(4)}-${hi.toFixed(4)}`,
    );
  });

  it("commits a drag to the selected species' window in the store; a live frame does not", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().selectSpecies(meta.id, fe.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot");
    const before = fe.windows.signal;

    fireEvent.click(screen.getByText("live-drag"));
    expect(
      useSpecies.getState().byImage[meta.id]!.find((s) => s.id === fe.id)!.windows
        .signal,
    ).toEqual(before);

    fireEvent.click(screen.getByText("commit-drag"));
    const after = useSpecies
      .getState()
      .byImage[meta.id]!.find((s) => s.id === fe.id)!.windows.signal;
    expect(after).not.toEqual(before);
    // locked by default: commit re-centres on the species' anchor (6.404),
    // it does not just widen the dragged bounds verbatim.
    expect((after.lo + after.hi) / 2).toBeCloseTo(fe.energy, 6);
  });

  it("typing a window bound commits directly through the store", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().selectSpecies(meta.id, fe.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot");

    // Unlocked, so the typed bound lands exactly where typed rather than
    // being re-centred on the species' anchor (see the locked-commit test).
    fireEvent.click(screen.getByRole("checkbox", { name: /Lock to line/ }));
    const loInput = screen.getByTitle(/Energy window low/);
    fireEvent.change(loInput, { target: { value: "6.2" } });

    const after = useSpecies
      .getState()
      .byImage[meta.id]!.find((s) => s.id === fe.id)!.windows.signal;
    expect(after.lo).toBeCloseTo(6.2, 6);
  });

  it("a width preset commits through the store", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().selectSpecies(meta.id, fe.id);
    const before = fe.windows.signal;

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot");

    fireEvent.click(screen.getByRole("button", { name: "wide" }));

    const after = useSpecies
      .getState()
      .byImage[meta.id]!.find((s) => s.id === fe.id)!.windows.signal;
    expect(after.hi - after.lo).toBeGreaterThan(before.hi - before.lo);
  });

  it("editing background and beam energy write the shared per-image EDS settings", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().selectSpecies(meta.id, fe.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot");

    fireEvent.click(screen.getByRole("button", { name: "brems" }));
    expect(useSpecies.getState().edsSettingsByImage[meta.id]?.bg).toBe(
      "bremsstrahlung",
    );

    const e0Input = screen.getByTitle(/Beam energy/);
    fireEvent.change(e0Input, { target: { value: "25" } });
    expect(useSpecies.getState().edsSettingsByImage[meta.id]?.e0Kev).toBe(25);
  });

  it("restores a pinned region onto its matching existing species", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    const si = edsSpecies("Si", "K", 1.74);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().addSpecies(meta.id, si);
    useSpecies.getState().selectSpecies(meta.id, si.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot"); // wait for the spectrum so integration is real

    fireEvent.click(screen.getByRole("button", { name: "+ Add region" }));
    // restore a DIFFERENT species' region — select back to Fe first so the
    // pinned Si row is the one under test.
    fireEvent.click(screen.getByRole("option", { name: "Fe" }));
    fireEvent.click(screen.getByRole("button", { name: "Si" }));

    expect(useSpecies.getState().selectedByImage[meta.id]).toBe(si.id);
    // no duplicate species was created for the restore
    expect(useSpecies.getState().byImage[meta.id]).toHaveLength(2);
  });

  it("restores a pinned region for a species the user removed by recreating it", async () => {
    const meta = openCube();
    const fe = edsSpecies("Fe", "K", 6.404);
    useSpecies.getState().addSpecies(meta.id, fe);
    useSpecies.getState().selectSpecies(meta.id, fe.id);

    render(<EdsSpectrumImage />);
    await screen.findByTestId("spectrum-plot"); // wait for the spectrum so integration is real
    fireEvent.click(screen.getByRole("button", { name: "+ Add region" }));

    // the user removes the species the region was pinned from
    useSpecies.getState().removeSpecies(meta.id, fe.id);
    expect(useSpecies.getState().byImage[meta.id]).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: "Fe" }));

    const list = useSpecies.getState().byImage[meta.id]!;
    expect(list).toHaveLength(1);
    expect(list[0].symbol).toBe("Fe");
    expect(useSpecies.getState().selectedByImage[meta.id]).toBe(list[0].id);
    expect(list[0].windows.signal.lo).toBeCloseTo(fe.windows.signal.lo, 4);
    expect(list[0].windows.signal.hi).toBeCloseTo(fe.windows.signal.hi, 4);
  });
});
