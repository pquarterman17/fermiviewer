import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../lib/api")>();
  return {
    ...actual,
    listFourD: vi.fn(),
    fetchFourDNav: vi.fn(),
    fetchFourDMeanPattern: vi.fn(),
    fetchData16: vi.fn(),
    computeVirtualDetector: vi.fn(),
  };
});

import type { FourDMeta, ImageMeta, Raster16 } from "../lib/api";
import {
  computeVirtualDetector,
  fetchData16,
  fetchFourDMeanPattern,
  fetchFourDNav,
  listFourD,
} from "../lib/api";
import { apertureError, apertureRadiiForMode, useFourD } from "./fourd";
import { useViewer } from "./viewer";

function fourdMeta(id = "d1", detShape: [number, number] = [640, 640]): FourDMeta {
  return {
    id,
    name: `${id}.mib`,
    is_fourd: true,
    source: null,
    scan_shape: [4, 5],
    det_shape: detShape,
    dtype: "uint16",
    scan_axes: [
      { scale: 1, origin: 0, units: "nm" },
      { scale: 1, origin: 0, units: "nm" },
    ],
    det_axes: [
      { scale: 1, origin: 0, units: "" },
      { scale: 1, origin: 0, units: "" },
    ],
    nav_available: true,
  };
}

function raster(w = 4, h = 4): Raster16 {
  return { data: new Uint16Array(w * h), w, h, vmin: 0, vmax: 1, nFrames: null };
}

function imageMeta(id = "nav1"): ImageMeta {
  return {
    id,
    name: `nav(${id})`,
    kind: "image",
    shape: [4, 5],
    dtype: "float64",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

afterEach(() => {
  vi.clearAllMocks();
  useFourD.getState().reset();
  useViewer.setState({ images: {}, order: [], activeId: null });
});

describe("apertureRadiiForMode", () => {
  it("presets BF as a circle at det/8, no inner radius", () => {
    expect(apertureRadiiForMode("bf", [640, 640])).toEqual({
      innerR: 0,
      outerR: 80,
      shape: "circle",
    });
  });

  it("presets ABF as an annulus between det/16 and det/8", () => {
    expect(apertureRadiiForMode("abf", [640, 640])).toEqual({
      innerR: 40,
      outerR: 80,
      shape: "annulus",
    });
  });

  it("presets ADF as an annulus between det/6 and det/2.5", () => {
    const r = apertureRadiiForMode("adf", [640, 640]);
    expect(r.shape).toBe("annulus");
    expect(r.innerR).toBeCloseTo(640 / 6, 6);
    expect(r.outerR).toBeCloseTo(256, 6);
  });

  it("uses the smaller detector dimension for a non-square detector", () => {
    expect(apertureRadiiForMode("bf", [200, 640])).toEqual({
      innerR: 0,
      outerR: 25,
      shape: "circle",
    });
  });

  it("custom is a pass-through that never overwrites the current radii", () => {
    const current = { innerR: 12, outerR: 34, shape: "annulus" as const };
    expect(apertureRadiiForMode("custom", [640, 640], current)).toBe(current);
  });

  it("stays non-degenerate (no zero radii, no error) on a tiny 8x8 detector", () => {
    const bf = apertureRadiiForMode("bf", [8, 8]);
    expect(bf).toEqual({ innerR: 0, outerR: 1, shape: "circle" });
    expect(apertureError({ ...bf, autoCenter: true, centerKy: null, centerKx: null }, [8, 8])).toBeNull();

    const abf = apertureRadiiForMode("abf", [8, 8]);
    expect(abf).toEqual({ innerR: 0.5, outerR: 1, shape: "annulus" });
    expect(apertureError({ ...abf, autoCenter: true, centerKy: null, centerKx: null }, [8, 8])).toBeNull();
  });
});

describe("apertureError", () => {
  const base = { innerR: 0, outerR: 10, shape: "circle" as const, autoCenter: true, centerKy: null, centerKx: null };

  it("accepts a valid auto-centered circle", () => {
    expect(apertureError(base, [640, 640])).toBeNull();
  });

  it("rejects a non-positive outer radius", () => {
    expect(apertureError({ ...base, outerR: 0 }, [640, 640])).toMatch(/outer radius/i);
    expect(apertureError({ ...base, outerR: -5 }, [640, 640])).toMatch(/outer radius/i);
  });

  it("rejects a negative inner radius on an annulus", () => {
    expect(
      apertureError({ ...base, shape: "annulus", innerR: -1, outerR: 10 }, [640, 640]),
    ).toMatch(/inner radius/i);
  });

  it("rejects inner >= outer on an annulus", () => {
    expect(
      apertureError({ ...base, shape: "annulus", innerR: 10, outerR: 10 }, [640, 640]),
    ).toMatch(/inner radius/i);
  });

  it("rejects a NaN manual center", () => {
    expect(
      apertureError({ ...base, autoCenter: false, centerKy: NaN, centerKx: 3 }, [640, 640]),
    ).toMatch(/center/i);
  });

  it("rejects a manual center outside the detector bounds", () => {
    expect(
      apertureError({ ...base, autoCenter: false, centerKy: -1, centerKx: 3 }, [640, 640]),
    ).toMatch(/detector bounds/i);
    expect(
      apertureError({ ...base, autoCenter: false, centerKy: 640, centerKx: 3 }, [640, 640]),
    ).toMatch(/detector bounds/i);
  });

  it("accepts a valid manual center", () => {
    expect(
      apertureError({ ...base, autoCenter: false, centerKy: 12.5, centerKx: 9 }, [640, 640]),
    ).toBeNull();
  });
});

describe("useFourD store", () => {
  it("fetchDatasets populates the list", async () => {
    vi.mocked(listFourD).mockResolvedValue([fourdMeta("d1")]);
    await useFourD.getState().fetchDatasets();
    expect(useFourD.getState().datasets).toEqual([fourdMeta("d1")]);
    expect(useFourD.getState().busyList).toBe(false);
  });

  it("selectDataset resets the aperture to the BF preset for that dataset's det_shape, and loads mean pattern + nav minimap", async () => {
    useFourD.setState({ datasets: [fourdMeta("d1", [320, 320])] });
    vi.mocked(fetchFourDMeanPattern).mockResolvedValue(raster(8, 8));
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster(4, 5));

    await act(() => useFourD.getState().selectDataset("d1"));

    const s = useFourD.getState();
    expect(s.selectedId).toBe("d1");
    expect(s.aperture).toEqual({
      centerKy: null,
      centerKx: null,
      autoCenter: true,
      mode: "bf",
      innerR: 0,
      outerR: 40, // 320 / 8
      shape: "circle",
    });
    expect(s.patternRaster).toEqual(raster(8, 8));
    expect(s.navMeta).toEqual(imageMeta("nav1"));
    expect(s.navRaster).toEqual(raster(4, 5));
    // dataset selection alone must NOT hijack the main viewer's active image
    expect(useViewer.getState().images.nav1).toBeUndefined();
  });

  it("showNavImage ingests the nav ImageMeta into the main viewer store", async () => {
    useFourD.setState({ datasets: [fourdMeta("d1")], selectedId: "d1" });
    vi.mocked(fetchFourDNav).mockResolvedValue(imageMeta("nav1"));
    vi.mocked(fetchData16).mockResolvedValue(raster());

    await act(() => useFourD.getState().showNavImage());

    expect(useViewer.getState().images.nav1).toBeDefined();
  });

  it("setApertureMode recomputes radii from the selected dataset's det_shape", () => {
    useFourD.setState({ datasets: [fourdMeta("d1", [800, 800])], selectedId: "d1" });
    useFourD.getState().setApertureMode("adf");
    const { aperture } = useFourD.getState();
    expect(aperture.mode).toBe("adf");
    expect(aperture.shape).toBe("annulus");
    expect(aperture.innerR).toBeCloseTo(800 / 6, 6);
    expect(aperture.outerR).toBeCloseTo(320, 6);
  });

  it("manually editing a radius flips the mode to custom without changing other fields", () => {
    useFourD.setState({ datasets: [fourdMeta("d1")], selectedId: "d1" });
    useFourD.getState().setApertureMode("bf");
    useFourD.getState().setApertureField({ outerR: 55 });
    const { aperture } = useFourD.getState();
    expect(aperture.mode).toBe("custom");
    expect(aperture.outerR).toBe(55);
    expect(aperture.shape).toBe("circle"); // untouched by the edit
  });

  it("computeMap sends center null when autoCenter is on, and ingests the result", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null,
        centerKx: null,
        autoCenter: true,
        mode: "bf",
        innerR: 0,
        outerR: 80,
        shape: "circle",
      },
    });
    vi.mocked(computeVirtualDetector).mockResolvedValue(imageMeta("map1"));

    await act(() => useFourD.getState().computeMap());

    expect(computeVirtualDetector).toHaveBeenCalledWith("d1", {
      center_ky: null,
      center_kx: null,
      inner_r: 0,
      outer_r: 80,
      shape: "circle",
      name: "bf(d1.mib)",
    });
    expect(useViewer.getState().images.map1).toBeDefined();
    expect(useFourD.getState().status).toContain("map computed");
  });

  it("computeMap sends the manual center when autoCenter is off", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: 12.5,
        centerKx: 9,
        autoCenter: false,
        mode: "custom",
        innerR: 5,
        outerR: 20,
        shape: "annulus",
      },
    });
    vi.mocked(computeVirtualDetector).mockResolvedValue(imageMeta("map2"));

    await act(() => useFourD.getState().computeMap());

    expect(computeVirtualDetector).toHaveBeenCalledWith("d1", {
      center_ky: 12.5,
      center_kx: 9,
      inner_r: 5,
      outer_r: 20,
      shape: "annulus",
      name: "custom(d1.mib)",
    });
  });

  it("computeMap ignores a second call while the first is still in flight (double-submit guard)", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "bf", innerR: 0, outerR: 80, shape: "circle",
      },
    });
    let resolveFetch: (m: ImageMeta) => void = () => {};
    vi.mocked(computeVirtualDetector).mockReturnValue(
      new Promise((resolve) => { resolveFetch = resolve; }),
    );

    const first = useFourD.getState().computeMap();
    const second = useFourD.getState().computeMap(); // fired before the first settles
    resolveFetch(imageMeta("map3"));
    await act(async () => {
      await Promise.all([first, second]);
    });

    expect(computeVirtualDetector).toHaveBeenCalledTimes(1);
  });

  it("computeMap refuses a non-finite/degenerate aperture instead of sending it to the server", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: NaN, centerKx: 9, autoCenter: false,
        mode: "custom", innerR: 5, outerR: 20, shape: "annulus",
      },
    });

    await act(() => useFourD.getState().computeMap());

    expect(computeVirtualDetector).not.toHaveBeenCalled();
    expect(useFourD.getState().status).toMatch(/center/i);
  });

  it("computeMap refuses a zero/negative outer radius", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "custom", innerR: 0, outerR: 0, shape: "circle",
      },
    });

    await act(() => useFourD.getState().computeMap());

    expect(computeVirtualDetector).not.toHaveBeenCalled();
    expect(useFourD.getState().status).toMatch(/outer radius/i);
  });

  it("computeMap refuses an annulus whose inner radius is not smaller than the outer radius", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "custom", innerR: 40, outerR: 40, shape: "annulus",
      },
    });

    await act(() => useFourD.getState().computeMap());

    expect(computeVirtualDetector).not.toHaveBeenCalled();
    expect(useFourD.getState().status).toMatch(/inner radius/i);
  });

  it("fetchDatasets drops a malformed dataset entry instead of letting it crash the picker", async () => {
    const malformed = { ...fourdMeta("bad"), det_shape: undefined } as unknown as FourDMeta;
    vi.mocked(listFourD).mockResolvedValue([fourdMeta("d1"), malformed]);

    await useFourD.getState().fetchDatasets();

    expect(useFourD.getState().datasets.map((d) => d.id)).toEqual(["d1"]);
  });
});
