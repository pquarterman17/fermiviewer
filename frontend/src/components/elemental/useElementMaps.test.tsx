import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { edsElementMaps } from "../../lib/api";
import { edsSpecies, type Species } from "../../lib/spectrum/species";
import { useEdsElementMaps } from "./useElementMaps";

vi.mock("../../lib/api", () => ({ edsElementMaps: vi.fn() }));

const isOpen = (id: string | null): id is string => !!id;

function reply(symbols: string[], shape: [number, number] = [2, 2]) {
  return {
    image_id: "cube",
    shape,
    bg: "linear",
    maps: symbols.map((symbol) => ({
      symbol,
      line: "K",
      energy_kev: 6.4,
      window: [6.3, 6.5] as [number, number],
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

function render(species: Species[], onStatus = vi.fn()) {
  return renderHook(
    (props: { species: Species[] }) =>
      useEdsElementMaps({
        imageId: "cube",
        species: props.species,
        bg: "linear",
        e0Kev: 20,
        isOpen,
        onStatus,
      }),
    { initialProps: { species } },
  );
}

afterEach(() => vi.clearAllMocks());

describe("useEdsElementMaps", () => {
  it("fetches N species in ONE request, not one request per species", async () => {
    // The whole point of plan #8/#9: five elements used to be five round trips
    // and five reads of the cube.
    vi.mocked(edsElementMaps).mockResolvedValue(reply(["Fe", "Si", "Cu"]));
    const species = [
      edsSpecies("Fe", "K", 6.404),
      edsSpecies("Si", "K", 1.74),
      edsSpecies("Cu", "K", 8.048),
    ];
    const { result } = render(species);

    await waitFor(() => expect(result.current.tiles).toHaveLength(3));
    expect(edsElementMaps).toHaveBeenCalledTimes(1);
    expect(vi.mocked(edsElementMaps).mock.calls[0][1]).toHaveLength(3);
  });

  it("sends each species' own window, so a tuned window is honoured", async () => {
    vi.mocked(edsElementMaps).mockResolvedValue(reply(["Fe"]));
    const fe = edsSpecies("Fe", "K", 6.404);
    fe.windows.signal = { lo: 6.0, hi: 6.8 };
    render([fe]);

    await waitFor(() => expect(edsElementMaps).toHaveBeenCalled());
    expect(vi.mocked(edsElementMaps).mock.calls[0][1]).toEqual([
      { symbol: "Fe", eLo: 6.0, eHi: 6.8 },
    ]);
  });

  it("requests only the newly added species, keeping the cached ones", async () => {
    vi.mocked(edsElementMaps).mockResolvedValue(reply(["Fe"]));
    const fe = edsSpecies("Fe", "K", 6.404);
    const { result, rerender } = render([fe]);
    await waitFor(() => expect(result.current.tiles).toHaveLength(1));

    vi.mocked(edsElementMaps).mockResolvedValue(reply(["Si"]));
    rerender({ species: [fe, edsSpecies("Si", "K", 1.74)] });

    await waitFor(() => expect(result.current.tiles).toHaveLength(2));
    expect(edsElementMaps).toHaveBeenCalledTimes(2);
    // the second call asks for Si alone — Fe came from the cache
    expect(vi.mocked(edsElementMaps).mock.calls[1][1]).toEqual([
      { symbol: "Si", eLo: expect.any(Number), eHi: expect.any(Number) },
    ]);
  });

  it("reports an unmappable species instead of dropping it silently", async () => {
    // The endpoint keeps the row with a reason; the montage cannot show a
    // raster that does not exist, so the reason has to reach the status bar.
    const onStatus = vi.fn();
    vi.mocked(edsElementMaps).mockResolvedValue({
      image_id: "cube",
      shape: [2, 2] as [number, number],
      bg: "linear",
      maps: [
        {
          symbol: "Mo",
          line: null,
          energy_kev: null,
          window: null,
          map: null,
          total_counts: null,
          map_meta: null,
          error: "Mo Kα line (17.479 keV) outside the energy axis",
        },
      ],
    });
    render([edsSpecies("Mo", "K", 17.479)], onStatus);

    await waitFor(() => expect(onStatus).toHaveBeenCalled());
    expect(onStatus.mock.calls[0][1]).toContain("Mo");
    expect(onStatus.mock.calls[0][1]).toContain("outside the energy axis");
  });

  it("issues no request at all when nothing is visible", async () => {
    const { result } = render([]);
    await waitFor(() => expect(result.current.tiles).toHaveLength(0));
    expect(edsElementMaps).not.toHaveBeenCalled();
  });
});
