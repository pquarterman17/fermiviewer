// exportActive (shared by the Export dialog + Export card): builds the
// /export payload from current store state and triggers a download.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const state = {
  activeId: "img1",
  images: {
    img1: {
      id: "img1",
      name: "a",
      kind: "image",
      shape: [10, 10],
      pixel_size: 1,
      pixel_unit: "nm",
    },
  },
  display: { img1: { lo: 0, hi: 1, gamma: 1, cmap: "gray" } },
  measures: {
    img1: [
      { id: "m1", kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }], width: 1 },
    ],
  },
  scaleBars: { img1: { x: 0.02, y: 0.92, lengthPhys: null, thickness: null, fontSize: null } },
  tilts: {},
  overlay: { size: "M", color: "#ffffff", endSymbol: "bar" },
};

vi.mock("../store/viewer", () => ({
  DEFAULT_DISPLAY: { lo: 0, hi: 1, gamma: 1, cmap: "gray" },
  useViewer: { getState: () => state },
}));

vi.mock("./api", () => ({
  exportImage: vi.fn(() =>
    Promise.resolve({ blob: new Blob(["x"]), filename: "a_export.png" }),
  ),
}));

import { exportImage } from "./api";
import { exportActive } from "./export";

describe("exportActive", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("bakes scale bar + measurements and returns the filename", async () => {
    const name = await exportActive({ format: "png", scale: 2 });
    expect(name).toBe("a_export.png");
    expect(exportImage).toHaveBeenCalledTimes(1);
    const [id, opts] = (exportImage as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, Record<string, unknown>];
    expect(id).toBe("img1");
    expect(opts.format).toBe("png");
    expect(opts.scale).toBe(2);
    expect(opts.include).toEqual(["scale_bar", "measurements"]);
    expect(opts.overlay_color).toBe("#ffffff");
    expect(opts.scale_bar_norm_x).toBe(0.02);
    expect((opts.measures as unknown[]).length).toBe(1);
  });

  it("omits scale bar + measurements for tiff16 (data export)", async () => {
    await exportActive({ format: "tiff16", scale: 1 });
    const [, opts] = (exportImage as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, Record<string, unknown>];
    expect(opts.include).toEqual([]);
    expect(opts.measures).toBeUndefined();
  });

  it("respects explicit opt-outs", async () => {
    await exportActive({ format: "png", scale: 1, scaleBar: false, measures: false });
    const [, opts] = (exportImage as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, Record<string, unknown>];
    expect(opts.include).toEqual([]);
  });
});
