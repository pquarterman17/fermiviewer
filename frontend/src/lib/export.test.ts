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
  overlay: { size: "M", color: "#ffffff", lineWidth: 2.5, endSymbol: "bar" },
};

vi.mock("../store/viewer", () => ({
  DEFAULT_DISPLAY: { lo: 0, hi: 1, gamma: 1, cmap: "gray" },
  OVERLAY_FONT_PX: { XS: 10, S: 13, M: 16, L: 20, XL: 26, XXL: 34 },
  useViewer: { getState: () => state },
}));

vi.mock("./api", () => ({
  exportImage: vi.fn(() =>
    Promise.resolve({ blob: new Blob(["x"]), filename: "a_export.png" }),
  ),
}));

import { exportImage } from "./api";
import { copyActive, exportActive, previewActive } from "./export";

type Calls = { mock: { calls: unknown[][] } };
const lastOpts = () =>
  (exportImage as unknown as Calls).mock.calls[0][1] as Record<string, unknown>;

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
    // burned measurements carry the on-screen overlay size + line width
    expect(opts.overlay_font_size).toBe(16); // mock overlay size "M" → 16px
    expect(opts.overlay_line_width).toBe(2.5);
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
    // styling fields ride along only when measurements are baked
    expect(opts.overlay_font_size).toBeUndefined();
    expect(opts.overlay_line_width).toBeUndefined();
  });
});

describe("caption (WS4c)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  });
  afterEach(() => vi.restoreAllMocks());

  it("adds 'caption' to include and sends the text", async () => {
    await exportActive({ format: "png", scale: 1, caption: "Fig 1 · HAADF" });
    const opts = lastOpts();
    expect(opts.include).toContain("caption");
    expect(opts.caption).toBe("Fig 1 · HAADF");
  });

  it("omits caption for tiff16 (no overlays) and when blank", async () => {
    await exportActive({ format: "tiff16", scale: 1, caption: "Fig 1" });
    expect(lastOpts().include).not.toContain("caption");
    expect(lastOpts().caption).toBeUndefined();

    vi.clearAllMocks();
    await exportActive({ format: "png", scale: 1, caption: "   " });
    expect(lastOpts().include).not.toContain("caption");
  });
});

describe("previewActive", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    globalThis.URL.createObjectURL = vi.fn(() => "blob:x");
    globalThis.URL.revokeObjectURL = vi.fn();
  });
  afterEach(() => vi.restoreAllMocks());

  it("forces png + scale 1, keeping the chosen format's gating", async () => {
    const blob = await previewActive({ format: "svg", scale: 4, caption: "C" });
    expect(blob).toBeInstanceOf(Blob);
    const opts = lastOpts();
    expect(opts.format).toBe("png"); // displayable in an <img>
    expect(opts.scale).toBe(1); // fast preview regardless of export scale
    expect(opts.include).toContain("caption"); // svg allows overlays
  });

  it("previews tiff16 bare, matching its real (overlay-free) export", async () => {
    await previewActive({ format: "tiff16", scale: 1, caption: "C" });
    const opts = lastOpts();
    expect(opts.format).toBe("png");
    expect(opts.include).toEqual([]);
  });
});

describe("copyActive", () => {
  const write = vi.fn(() => Promise.resolve());
  beforeEach(() => {
    vi.clearAllMocks();
    // jsdom ships neither clipboard.write nor ClipboardItem — stub both
    (globalThis as unknown as { ClipboardItem: unknown }).ClipboardItem =
      class {
        constructor(public items: unknown) {}
      };
    Object.defineProperty(globalThis.navigator, "clipboard", {
      configurable: true,
      value: { write },
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("defaults to a PNG with scale bar + measurements baked in", async () => {
    await copyActive();
    const [, opts] = (exportImage as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, Record<string, unknown>];
    expect(opts.format).toBe("png");
    expect(opts.include).toEqual(["scale_bar", "measurements"]);
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("respects explicit opt-outs", async () => {
    await copyActive({ format: "png", scale: 1, scaleBar: false, measures: false });
    const [, opts] = (exportImage as unknown as { mock: { calls: unknown[][] } })
      .mock.calls[0] as [string, Record<string, unknown>];
    expect(opts.include).toEqual([]);
  });
});
