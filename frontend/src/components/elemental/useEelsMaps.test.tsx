import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { eelsMaps } from "../../lib/api";
import { eelsSpecies, type Species } from "../../lib/spectrum/species";
import { useEelsElementMaps } from "./useEelsMaps";

vi.mock("../../lib/api", () => ({ eelsMaps: vi.fn() }));

const isOpen = (id: string | null): id is string => !!id;

function reply(labels: string[], shape: [number, number] = [2, 2]) {
  return {
    image_id: "cube",
    shape,
    maps: labels.map((label) => ({
      label,
      signal_window: [700, 750] as [number, number],
      background_window: [650, 698] as [number, number],
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

function render(species: Species[], onStatus = vi.fn()) {
  return renderHook(
    (props: { species: Species[] }) =>
      useEelsElementMaps({
        imageId: "cube",
        species: props.species,
        method: "powerlaw",
        isOpen,
        onStatus,
      }),
    { initialProps: { species } },
  );
}

afterEach(() => vi.clearAllMocks());

describe("useEelsElementMaps", () => {
  it("fetches N species in ONE request, not one request per species", async () => {
    vi.mocked(eelsMaps).mockResolvedValue(reply(["Fe-L23", "O-K", "Si-K"]));
    const species = [
      eelsSpecies("Fe", "L23", 708),
      eelsSpecies("O", "K", 532),
      eelsSpecies("Si", "K", 1839),
    ];
    const { result } = render(species);

    await waitFor(() => expect(result.current.tiles).toHaveLength(3));
    expect(eelsMaps).toHaveBeenCalledTimes(1);
    expect(vi.mocked(eelsMaps).mock.calls[0][1]).toHaveLength(3);
  });

  it("sends each species' own signal AND background window", async () => {
    vi.mocked(eelsMaps).mockResolvedValue(reply(["Fe-L23"]));
    const fe = eelsSpecies("Fe", "L23", 708);
    fe.windows.signal = { lo: 700, hi: 760 };
    fe.windows.background = { lo: 640, hi: 698 };
    render([fe]);

    await waitFor(() => expect(eelsMaps).toHaveBeenCalled());
    expect(vi.mocked(eelsMaps).mock.calls[0][1]).toEqual([
      {
        label: "Fe-L23",
        signal: { lo: 700, hi: 760 },
        background: { lo: 640, hi: 698 },
        method: "powerlaw",
      },
    ]);
  });

  it("omits background when the species has none set", async () => {
    vi.mocked(eelsMaps).mockResolvedValue(reply(["Fe-L23"]));
    const fe = eelsSpecies("Fe", "L23", 708);
    delete fe.windows.background;
    render([fe]);

    await waitFor(() => expect(eelsMaps).toHaveBeenCalled());
    expect(vi.mocked(eelsMaps).mock.calls[0][1][0].background).toBeUndefined();
  });

  it("requests only the newly added species, keeping the cached ones", async () => {
    vi.mocked(eelsMaps).mockResolvedValue(reply(["Fe-L23"]));
    const fe = eelsSpecies("Fe", "L23", 708);
    const { result, rerender } = render([fe]);
    await waitFor(() => expect(result.current.tiles).toHaveLength(1));

    vi.mocked(eelsMaps).mockResolvedValue(reply(["Si-K"]));
    rerender({ species: [fe, eelsSpecies("Si", "K", 1839)] });

    await waitFor(() => expect(result.current.tiles).toHaveLength(2));
    expect(eelsMaps).toHaveBeenCalledTimes(2);
    // the second call asks for Si-K alone — Fe-L23 came from the cache
    expect(vi.mocked(eelsMaps).mock.calls[1][1]).toHaveLength(1);
    expect(vi.mocked(eelsMaps).mock.calls[1][1][0].label).toBe("Si-K");
  });

  it("keeps two edges of the same element apart in the cache", async () => {
    // Si K and Si L23 share a symbol but must not collapse to one cache slot.
    vi.mocked(eelsMaps).mockResolvedValue(reply(["Si-L23", "Si-K"]));
    const species = [eelsSpecies("Si", "L23", 99), eelsSpecies("Si", "K", 1839)];
    const { result } = render(species);

    await waitFor(() => expect(result.current.tiles).toHaveLength(2));
    expect(result.current.tiles.map((t) => t.line)).toEqual(["L23", "K"]);
  });

  it("reports an unmappable species instead of dropping it silently", async () => {
    const onStatus = vi.fn();
    vi.mocked(eelsMaps).mockResolvedValue({
      image_id: "cube",
      shape: [2, 2] as [number, number],
      maps: [
        {
          label: "Mo-M45",
          signal_window: null,
          background_window: null,
          method: "powerlaw",
          map: null,
          total_counts: null,
          map_meta: null,
          error: "signal window [200.000, 250.000] eV is outside the energy axis",
        },
      ],
    });
    render([eelsSpecies("Mo", "M45", 227)], onStatus);

    await waitFor(() => expect(onStatus).toHaveBeenCalled());
    expect(onStatus.mock.calls[0][1]).toContain("Mo-M45");
    expect(onStatus.mock.calls[0][1]).toContain("outside the energy axis");
  });

  it("issues no request at all when nothing is visible", async () => {
    const { result } = render([]);
    await waitFor(() => expect(result.current.tiles).toHaveLength(0));
    expect(eelsMaps).not.toHaveBeenCalled();
  });
});
