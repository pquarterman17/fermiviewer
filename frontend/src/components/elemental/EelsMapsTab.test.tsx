import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { eelsAutoAssign, eelsMaps, fetchSpectrum, type ImageMeta } from "../../lib/api";
import { useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import EelsMapsTab from "./EelsMapsTab";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    eelsAutoAssign: vi.fn(),
    eelsMaps: vi.fn(),
    fetchSpectrum: vi.fn(),
  };
});

function cube(): ImageMeta {
  return {
    id: "cube",
    name: "cube.dm4",
    kind: "spectrum_image",
    shape: [4, 4, 4],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "",
    n_channels: 4,
    energy_first: 0,
    energy_last: 2000,
    energy_units: "eV",
    stage_tilt_deg: null,
    meta: {},
  } as ImageMeta;
}

/** One strong edge (auto-ticked) and one trace edge (present, unticked) —
 *  the same above-trace seeding contract EDS's identify() honours. */
function autoAssignReply() {
  return {
    edges: [
      {
        element: "Fe",
        edge: "L23",
        symbol: "Fe-L23",
        onset_ev: 708,
        fit_window: [656, 706] as [number, number],
        signal_window: [708, 758] as [number, number],
        net: 5000,
        sigma: 50,
        significance: 100,
        confidence: "strong" as const,
      },
      {
        element: "O",
        edge: "K",
        symbol: "O-K",
        onset_ev: 532,
        fit_window: [480, 530] as [number, number],
        signal_window: [532, 582] as [number, number],
        net: 300,
        sigma: 30,
        significance: 5,
        confidence: "trace" as const,
      },
    ],
  };
}

/** Hand-computable synthetic spectrum for the live-net tests below: the
 *  energy grid has no point inside Fe-L23's fit window [656,706] (auto-ID's
 *  own pre-edge background window from `autoAssignReply`), so `integrateEdge`
 *  takes its "< 2 channels — background skipped" path and net is exactly the
 *  gross sum over the signal window — no power-law fit to hand-replicate. */
function spectrumReply() {
  return {
    energy: [100, 300, 500, 708, 758, 900],
    counts: [5, 5, 5, 300, 200, 5],
    units: "eV",
  };
}

function mapsReply(labels: string[]) {
  return {
    image_id: "cube",
    shape: [4, 4] as [number, number],
    maps: labels.map((label) => ({
      label,
      signal_window: [708, 758] as [number, number],
      background_window: [656, 706] as [number, number],
      method: "powerlaw",
      map: [
        [1, 2],
        [3, 4],
      ],
      total_counts: 10,
      map_meta: null,
      error: null,
    })),
  };
}

beforeEach(() => {
  useViewer.getState().ingest([cube()]);
  useViewer.getState().setActive("cube");
});

afterEach(() => {
  useViewer.setState({ images: {}, order: [], activeId: null, selected: [] });
  useSpecies.setState({ byImage: {}, selectedByImage: {}, edsSettingsByImage: {} });
  vi.clearAllMocks();
});

describe("EelsMapsTab", () => {
  it("auto-identifies on open: strong edge ticked, trace edge present but not", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["Fe-L23"]));
    render(<EelsMapsTab />);

    await waitFor(() => expect(screen.getByLabelText("Show Fe")).toBeChecked());
    expect(screen.getByLabelText("Show O")).not.toBeChecked();
    // item 6: the edge, not just the element, and in eV
    expect(screen.getByText("L23")).toBeVisible();
    expect(screen.getByText("708 eV")).toBeVisible();
  });

  it("extracts and montages the ticked species, enabling export", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["Fe-L23"]));
    render(<EelsMapsTab />);

    await waitFor(() => expect(eelsMaps).toHaveBeenCalled());
    expect(vi.mocked(eelsMaps).mock.calls[0][1]).toEqual([
      expect.objectContaining({ label: "Fe-L23" }),
    ]);
    await waitFor(() =>
      expect(
        screen.getByRole("group", { name: "Element map montage" }),
      ).toBeVisible(),
    );
    expect(screen.getByRole("button", { name: "Export figure" })).toBeEnabled();
  });

  it("ticking a second edge requests only that edge — the first came from cache", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["Fe-L23"]));
    render(<EelsMapsTab />);
    await waitFor(() => expect(screen.getByLabelText("Show Fe")).toBeChecked());
    await waitFor(() => expect(eelsMaps).toHaveBeenCalledTimes(1));

    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["O-K"]));
    fireEvent.click(screen.getByLabelText("Show O"));

    await waitFor(() => expect(eelsMaps).toHaveBeenCalledTimes(2));
    expect(vi.mocked(eelsMaps).mock.calls[1][1]).toEqual([
      expect.objectContaining({ label: "O-K" }),
    ]);
  });

  it("reports plainly when nothing was identified", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue({ edges: [] });
    render(<EelsMapsTab />);
    await waitFor(() =>
      expect(screen.getByText(/No elements identified/)).toBeVisible(),
    );
    expect(eelsMaps).not.toHaveBeenCalled();
  });

  it("re-picking a removed element from the periodic table restores every edge for it", async () => {
    // Si has two edges in range at once — both get seeded from evidence on
    // open (item 1: the auto-assign response IS the in-range edge table), so
    // this exercises the picker's own add path by removing both first, then
    // re-adding via the symbol click, which must restore both, not force a
    // single-line choice the way EDS's edsLineEnergy lookup does.
    vi.mocked(eelsAutoAssign).mockResolvedValue({
      edges: [
        {
          element: "Si", edge: "L23", symbol: "Si-L23", onset_ev: 99,
          fit_window: [47, 97] as [number, number],
          signal_window: [99, 149] as [number, number],
          net: 400, sigma: 40, significance: 10, confidence: "weak" as const,
        },
        {
          element: "Si", edge: "K", symbol: "Si-K", onset_ev: 1839,
          fit_window: [1787, 1837] as [number, number],
          signal_window: [1839, 1889] as [number, number],
          net: 200, sigma: 40, significance: 5, confidence: "trace" as const,
        },
      ],
    });
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply([]));
    render(<EelsMapsTab />);
    await waitFor(() =>
      expect(screen.getAllByLabelText("Show Si")).toHaveLength(2),
    );

    while (screen.queryAllByLabelText("Remove Si").length > 0) {
      fireEvent.click(screen.getAllByLabelText("Remove Si")[0]);
    }
    await waitFor(() =>
      expect(screen.queryAllByLabelText("Show Si")).toHaveLength(0),
    );

    fireEvent.click(screen.getByRole("button", { name: "+ Add" }));
    fireEvent.click(screen.getByRole("button", { name: /^Si/ }));

    await waitFor(() =>
      expect(screen.getAllByLabelText("Show Si")).toHaveLength(2),
    );
  });
});

describe("EelsMapsTab live net", () => {
  it("computes a hand-matching live net ± sigma, and updates it without a re-identify", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["Fe-L23"]));

    render(<EelsMapsTab />);

    // signal [708,758] -> channels 708,758 -> gross 300+200=500, no
    // background fit (0 channels in [656,706]) -> net=500, sqrt(500)=22.36.
    await waitFor(() => expect(screen.getByText("500 ± 22")).toBeVisible());

    // Drag the window wider directly through the store — the same thing
    // EelsExploreTab's commitWindows does — WITHOUT calling identify again.
    // Every channel now qualifies: 5+5+5+300+200+5 = 520, sqrt(520)=22.80.
    const speciesId = useSpecies.getState().byImage.cube[0].id;
    act(() => {
      useSpecies.getState().setWindow("cube", speciesId, "signal", { lo: 100, hi: 900 });
    });

    await waitFor(() => expect(screen.getByText("520 ± 23")).toBeVisible());
    // The stale identify-time net must be gone, not just superseded in the DOM.
    expect(screen.queryByText("500 ± 22")).toBeNull();
  });

  it("shows the identifying placeholder, not a stale net, before the first identify resolves", () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue({ edges: [] });
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    render(<EelsMapsTab />);
    expect(screen.getByText("Identifying…")).toBeVisible();
  });
});

describe("EelsMapsTab row selection", () => {
  it("selects a row's species in the store when its symbol is clicked, and highlights it", async () => {
    vi.mocked(eelsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    vi.mocked(eelsMaps).mockResolvedValue(mapsReply(["Fe-L23"]));

    render(<EelsMapsTab />);
    await waitFor(() => expect(screen.getByLabelText("Show Fe")).toBeVisible());

    expect(useSpecies.getState().selectedByImage.cube).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Fe" }));

    const speciesId = useSpecies.getState().byImage.cube[0].id;
    expect(useSpecies.getState().selectedByImage.cube).toBe(speciesId);
    expect(screen.getByLabelText("Show Fe").closest("li")).toHaveClass("selected");
  });
});
