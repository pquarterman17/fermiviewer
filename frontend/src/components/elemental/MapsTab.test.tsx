import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { edsAutoAssign, edsElementMaps, fetchSpectrum, type ImageMeta } from "../../lib/api";
import { useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import MapsTab from "./MapsTab";

vi.mock("../../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../../lib/api")>();
  return {
    ...actual,
    edsAutoAssign: vi.fn(),
    fetchSpectrum: vi.fn(),
    edsElementMaps: vi.fn(),
  };
});

function cube(): ImageMeta {
  return {
    id: "cube",
    name: "cube.dm4",
    kind: "spectrum_image",
    shape: [4, 4, 7],
    dtype: "float32",
    pixel_size: 1,
    pixel_unit: "nm",
    value_unit: "",
    n_channels: 7,
    energy_first: 1.6,
    energy_last: 1.9,
    energy_units: "keV",
    stage_tilt_deg: null,
    meta: {},
  } as ImageMeta;
}

/** One candidate for Si K at 1.74 keV, the only element auto-assign finds. */
function autoAssignReply() {
  return {
    peaks_kev: [1.74],
    assignments: [
      {
        peak_kev: 1.74,
        candidates: [{ symbol: "Si", line: "K", energy_kev: 1.74, delta_kev: 0.002 }],
      },
    ],
  };
}

/** Hand-computable synthetic spectrum: with bg="none", the net over a
 *  window is exactly the sum of the counts whose energy falls in it. */
function spectrumReply() {
  return {
    energy: [1.6, 1.65, 1.7, 1.74, 1.78, 1.82, 1.9],
    counts: [10, 20, 30, 100, 40, 20, 10],
    units: "keV",
  };
}

function mapsReply(symbols: string[]) {
  return {
    image_id: "cube",
    shape: [2, 2] as [number, number],
    bg: "none",
    maps: symbols.map((symbol) => ({
      symbol,
      line: "K",
      energy_kev: 1.74,
      window: [1.655, 1.825] as [number, number],
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

describe("MapsTab live net", () => {
  it("computes a hand-matching live net ± sigma, and updates it without a re-identify", async () => {
    // bg="none" so net is exactly the gross sum over the window — no
    // background model to hand-replicate in the test.
    vi.mocked(edsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    vi.mocked(edsElementMaps).mockResolvedValue(mapsReply(["Si"]));

    render(<MapsTab bg="none" e0Kev={30} />);

    // Seeded window is [1.655, 1.825] (1.74 keV line ± the 0.085 keV
    // default half-width) → channels 1.70, 1.74, 1.78, 1.82 → 30+100+40+20.
    await waitFor(() => expect(screen.getByText("190 ± 14")).toBeVisible());

    // Drag the window wider directly through the store — the same thing a
    // later wave's Explore window-drag will do — WITHOUT calling identify
    // again. Every channel now qualifies: 10+20+30+100+40+20+10 = 230.
    const speciesId = useSpecies.getState().byImage.cube[0].id;
    act(() => {
      useSpecies.getState().setWindow("cube", speciesId, "signal", { lo: 1.6, hi: 1.95 });
    });

    await waitFor(() => expect(screen.getByText("230 ± 15")).toBeVisible());
    // The stale identify-time net must be gone, not just superseded in the DOM.
    expect(screen.queryByText("190 ± 14")).toBeNull();
  });

  it("shows the identifying placeholder, not a stale net, before the first identify resolves", () => {
    vi.mocked(edsAutoAssign).mockResolvedValue({ peaks_kev: [], assignments: [] });
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    render(<MapsTab bg="none" e0Kev={30} />);
    // identify() is still in flight synchronously after mount — no row, no
    // net, just the busy state. The em-dash placeholder for a genuinely
    // empty live net is covered at the ElementList unit-test level.
    expect(screen.getByText("Identifying…")).toBeVisible();
  });
});

describe("MapsTab row selection", () => {
  it("selects a row's species in the store when its symbol is clicked, and highlights it", async () => {
    vi.mocked(edsAutoAssign).mockResolvedValue(autoAssignReply());
    vi.mocked(fetchSpectrum).mockResolvedValue(spectrumReply());
    vi.mocked(edsElementMaps).mockResolvedValue(mapsReply(["Si"]));

    render(<MapsTab bg="none" e0Kev={30} />);
    await waitFor(() => expect(screen.getByLabelText("Show Si")).toBeVisible());

    expect(useSpecies.getState().selectedByImage.cube).toBeUndefined();
    fireEvent.click(screen.getByRole("button", { name: "Si" }));

    const speciesId = useSpecies.getState().byImage.cube[0].id;
    expect(useSpecies.getState().selectedByImage.cube).toBe(speciesId);
    expect(screen.getByLabelText("Show Si").closest("li")).toHaveClass("selected");
  });
});
