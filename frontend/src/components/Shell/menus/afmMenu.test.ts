// Three-point levelling turns the last angle/triangle measure's normalized
// points into pixel indices; edge points must stay inside the image.
import { describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../../../lib/api";
import { buildAfmMenu, pixelIndex, threePointPixels } from "./afmMenu";
import type { Entry, MenuCtx } from "./menuTypes";

function image(extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id: "height", name: "Height", kind: "image", shape: [64, 64], dtype: "float64",
    pixel_size: 1, pixel_unit: "nm", value_unit: "nm", n_channels: null,
    energy_first: null, energy_last: null, energy_units: "", stage_tilt_deg: null,
    meta: { parser: "nanoscope", spm_channel_kind: "height" }, ...extra,
  };
}

function afmMenu(meta: ImageMeta | null = image()) {
  const store = {
    activeId: meta?.id ?? null,
    images: meta ? { [meta.id]: meta } : {},
    measures: {},
    openTool: vi.fn(),
    setStatus: vi.fn(),
    ingestDerived: vi.fn(),
  } as unknown as MenuCtx["store"];
  const menu = buildAfmMenu({ store } as unknown as MenuCtx);
  return { menu, store };
}

function submenu(menu: Entry, label: string): Entry[] {
  const entry = menu.submenu?.find((item) => item.label === label);
  if (!entry?.submenu) throw new Error(`missing ${label} submenu`);
  return entry.submenu;
}

describe("threePointPixels", () => {
  it("maps a bottom/right-edge point (x = y = 1) to the last pixel", () => {
    expect(pixelIndex(1, 64)).toBe(63);
    expect(pixelIndex(0, 64)).toBe(0);
    expect(threePointPixels([{ x: 1, y: 1 }, { x: 0, y: 1 }, { x: 1, y: 0 }], [64, 128]))
      .toEqual([[63, 127], [63, 0], [0, 127]]);
  });

  it("returns the pixel that contains an interior point", () => {
    expect(threePointPixels([{ x: 0.5, y: 0.25 }], [64, 128])).toEqual([[16, 64]]);
    expect(pixelIndex(0.999, 64)).toBe(63);
  });
});

describe("AFM menu organization", () => {
  it("groups preparation, channels, analysis, mechanics, and visualization", () => {
    const { menu } = afmMenu();
    expect(menu.submenu?.map((entry) => entry.label)).toEqual([
      "Prepare", "Channels", "Surface Analysis", "Mechanical", "Visualize & Segment",
    ]);
    expect(submenu(menu, "Surface Analysis").map((entry) => entry.label)).toEqual([
      "ISO 25178 & Surface Maps…", "2-D Power Spectrum…", "Autocorrelation…", "Step Height…",
    ]);
  });

  it("routes every surface entry through the same guided workspace", () => {
    const { menu, store } = afmMenu();
    const surface = submenu(menu, "Surface Analysis");
    surface.slice(0, 3).forEach((entry) => entry.action?.());
    expect(store.openTool).toHaveBeenNthCalledWith(1, "afmsurface");
    expect(store.openTool).toHaveBeenNthCalledWith(2, "afmsurface");
    expect(store.openTool).toHaveBeenNthCalledWith(3, "afmsurface");
    surface[3].action?.();
    expect(store.openTool).toHaveBeenLastCalledWith("afmstep");
  });

  it("disables height-only commands for another SPM channel", () => {
    const phase = image({
      id: "phase", value_unit: "deg",
      meta: { parser: "nanoscope", spm_channel_kind: "other" },
    });
    const { menu } = afmMenu(phase);
    expect(menu.submenu?.find((entry) => entry.label === "Prepare")?.disabled).toBe(true);
    expect(menu.submenu?.find((entry) => entry.label === "Channels")?.disabled).toBe(false);
    expect(menu.submenu?.find((entry) => entry.label === "Surface Analysis")?.disabled).toBe(true);
    expect(menu.submenu?.find((entry) => entry.label === "Visualize & Segment")?.disabled).toBe(true);
    expect(submenu(menu, "Prepare").every((entry) => entry.disabled)).toBe(true);
    expect(submenu(menu, "Channels")[0].disabled).toBe(false);
    expect(submenu(menu, "Surface Analysis").every((entry) => entry.disabled)).toBe(true);
    expect(submenu(menu, "Visualize & Segment").every((entry) => entry.disabled)).toBe(true);
  });
});
