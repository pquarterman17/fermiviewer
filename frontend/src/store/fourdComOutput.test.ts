import { act } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", async (importActual) => {
  const actual = await importActual<typeof import("../lib/api")>();
  return {
    ...actual,
    computeCom: vi.fn(),
    computeDpc: vi.fn(),
    computeIdpc: vi.fn(),
    listFourD: vi.fn(),
  };
});

import type { FourDMeta, ImageMeta } from "../lib/api";
import { computeCom, computeDpc, computeIdpc, FourDNotFoundError, listFourD } from "../lib/api";
import { useFourD } from "./fourd";
import { comOutputError, DEFAULT_HIGH_PASS_CUTOFF, isComOutputMode } from "./fourdComOutput";
import { useViewer } from "./viewer";

function fourdMeta(id = "d1", detShape: [number, number] = [21, 21]): FourDMeta {
  return {
    id,
    name: `${id}.mib`,
    is_fourd: true,
    source: null,
    scan_shape: [3, 3],
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
    n_frames: 9,
    scan_shape_from_file: true,
    scan_shape_options: [],
  };
}

function imageMeta(id: string): ImageMeta {
  return {
    id,
    name: id,
    kind: "image",
    shape: [3, 3],
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

// ════════════════════════════════════════════════════════════════════
// isComOutputMode
// ════════════════════════════════════════════════════════════════════

describe("isComOutputMode", () => {
  it("is true for com/dpc/idpc", () => {
    expect(isComOutputMode("com")).toBe(true);
    expect(isComOutputMode("dpc")).toBe(true);
    expect(isComOutputMode("idpc")).toBe(true);
  });

  it("is false for the aperture-based modes", () => {
    expect(isComOutputMode("bf")).toBe(false);
    expect(isComOutputMode("abf")).toBe(false);
    expect(isComOutputMode("adf")).toBe(false);
    expect(isComOutputMode("custom")).toBe(false);
  });
});

// ════════════════════════════════════════════════════════════════════
// comOutputError
// ════════════════════════════════════════════════════════════════════

describe("comOutputError", () => {
  const detShape: [number, number] = [21, 21];

  it("accepts com mode with auto-center and no calibration at all", () => {
    expect(comOutputError("com", null, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toBeNull();
  });

  it("requires a manual center when auto-center is off", () => {
    expect(
      comOutputError("com", null, DEFAULT_HIGH_PASS_CUTOFF, false, null, null, detShape),
    ).toMatch(/center \(ky, kx\) must be set/);
  });

  it("rejects a manual center outside the detector bounds", () => {
    expect(
      comOutputError("com", null, DEFAULT_HIGH_PASS_CUTOFF, false, 5, 999, detShape),
    ).toMatch(/detector bounds/);
  });

  it("accepts a valid manual center for com (no calibration needed)", () => {
    expect(
      comOutputError("com", null, DEFAULT_HIGH_PASS_CUTOFF, false, 10, 10, detShape),
    ).toBeNull();
  });

  it("requires mrad/px for dpc, even with a valid center", () => {
    expect(
      comOutputError("dpc", null, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape),
    ).toMatch(/mrad\/px/);
  });

  it("rejects a non-positive mrad/px for dpc", () => {
    expect(comOutputError("dpc", 0, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toMatch(
      /mrad\/px/,
    );
    expect(comOutputError("dpc", -1, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toMatch(
      /mrad\/px/,
    );
  });

  it("accepts dpc with a valid mrad/px", () => {
    expect(comOutputError("dpc", 2.0, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toBeNull();
  });

  it("does not require mrad/px for com (only dpc/idpc need it)", () => {
    expect(comOutputError("com", null, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toBeNull();
  });

  it("requires mrad/px for idpc too", () => {
    expect(comOutputError("idpc", null, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toMatch(
      /mrad\/px/,
    );
  });

  it("rejects a negative high-pass cutoff for idpc", () => {
    expect(comOutputError("idpc", 2.0, -0.01, true, null, null, detShape)).toMatch(
      /high-pass cutoff/,
    );
  });

  it("accepts a zero high-pass cutoff for idpc (explicitly allowed — disables suppression)", () => {
    expect(comOutputError("idpc", 2.0, 0, true, null, null, detShape)).toBeNull();
  });

  it("does not check high-pass cutoff for dpc (only idpc uses it)", () => {
    expect(comOutputError("dpc", 2.0, -5, true, null, null, detShape)).toBeNull();
  });

  it("accepts idpc with a valid mrad/px and cutoff", () => {
    expect(comOutputError("idpc", 2.0, DEFAULT_HIGH_PASS_CUTOFF, true, null, null, detShape)).toBeNull();
  });
});

// ════════════════════════════════════════════════════════════════════
// computeComOutput
// ════════════════════════════════════════════════════════════════════

describe("computeComOutput", () => {
  it("com mode: calls computeCom and ingests both maps", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "com", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: null, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });
    vi.mocked(computeCom).mockResolvedValue({ comy: imageMeta("comy1"), comx: imageMeta("comx1") });

    await act(() => useFourD.getState().computeComOutput());

    expect(computeCom).toHaveBeenCalledWith("d1", {
      center_ky: null,
      center_kx: null,
      name: "com(d1.mib)",
    });
    expect(useViewer.getState().images.comy1).toBeDefined();
    expect(useViewer.getState().images.comx1).toBeDefined();
    expect(useFourD.getState().status).toContain("com computed");
  });

  it("dpc mode: sends mrad_per_px and ingests all three maps", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: 10, centerKx: 10, autoCenter: false,
        mode: "dpc", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: 2.5, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });
    vi.mocked(computeDpc).mockResolvedValue({
      magnitude: imageMeta("mag1"),
      direction: imageMeta("dir1"),
      divergence: imageMeta("div1"),
    });

    await act(() => useFourD.getState().computeComOutput());

    expect(computeDpc).toHaveBeenCalledWith("d1", {
      center_ky: 10,
      center_kx: 10,
      mrad_per_px: 2.5,
      name: "dpc(d1.mib)",
    });
    expect(Object.keys(useViewer.getState().images).sort()).toEqual(["dir1", "div1", "mag1"]);
  });

  it("idpc mode: sends mrad_per_px and high_pass_cutoff, ingests the single map", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "idpc", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: 1.5, highPassCutoff: 0.05,
      },
    });
    vi.mocked(computeIdpc).mockResolvedValue(imageMeta("idpc1"));

    await act(() => useFourD.getState().computeComOutput());

    expect(computeIdpc).toHaveBeenCalledWith("d1", {
      center_ky: null,
      center_kx: null,
      mrad_per_px: 1.5,
      high_pass_cutoff: 0.05,
      name: "idpc(d1.mib)",
    });
    expect(useViewer.getState().images.idpc1).toBeDefined();
  });

  it("refuses an invalid request instead of calling the server", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "dpc", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: null, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });

    await act(() => useFourD.getState().computeComOutput());

    expect(computeDpc).not.toHaveBeenCalled();
    expect(useFourD.getState().status).toMatch(/mrad\/px/);
  });

  it("is a no-op when the aperture mode is not a com-output mode (bf/abf/adf/custom)", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "bf", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: null, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });

    await act(() => useFourD.getState().computeComOutput());

    expect(computeCom).not.toHaveBeenCalled();
    expect(computeDpc).not.toHaveBeenCalled();
    expect(computeIdpc).not.toHaveBeenCalled();
  });

  it("ignores a second call while the first is still in flight (double-submit guard)", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "com", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: null, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });
    let resolveFetch: (m: { comy: ImageMeta; comx: ImageMeta }) => void = () => {};
    vi.mocked(computeCom).mockReturnValue(
      new Promise((resolve) => { resolveFetch = resolve; }),
    );

    const first = useFourD.getState().computeComOutput();
    const second = useFourD.getState().computeComOutput(); // fired before the first settles
    resolveFetch({ comy: imageMeta("comy2"), comx: imageMeta("comx2") });
    await act(async () => {
      await Promise.all([first, second]);
    });

    expect(computeCom).toHaveBeenCalledTimes(1);
  });

  it("refreshes the dataset list on a stale-dataset 404 instead of a raw error status", async () => {
    useFourD.setState({
      datasets: [fourdMeta("d1")],
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "com", innerR: 0, outerR: 1, shape: "circle",
        mradPerPx: null, highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      },
    });
    vi.mocked(computeCom).mockRejectedValue(new FourDNotFoundError("unknown 4D dataset id: d1"));
    vi.mocked(listFourD).mockResolvedValue([]);

    await act(() => useFourD.getState().computeComOutput());

    expect(listFourD).toHaveBeenCalledOnce();
    expect(useFourD.getState().selectedId).toBeNull();
  });
});
