// loadPixels — the one kind→endpoint branch for GPU uploads (ADR 0003 §5).
// The mode selection is what's testable in jsdom; the shader itself is not.

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../lib/api", () => ({
  fetchData16: vi.fn(),
  fetchRgb8: vi.fn(),
}));

import { fetchData16, fetchRgb8, type Raster16 } from "../lib/api";
import { loadImagePixels } from "./loadPixels";
import type { GLRenderer } from "./render";

function fakeGl() {
  return {
    setImage16: vi.fn(),
    setImageRgb8: vi.fn(),
  } as unknown as GLRenderer;
}

const raster16: Raster16 = {
  data: new Uint16Array(6),
  w: 3,
  h: 2,
  vmin: 0,
  vmax: 1,
  nFrames: null,
};

beforeEach(() => {
  vi.mocked(fetchData16).mockReset().mockResolvedValue(raster16);
  vi.mocked(fetchRgb8)
    .mockReset()
    .mockResolvedValue({ data: new Uint8Array(18), w: 3, h: 2 });
});

describe("loadImagePixels", () => {
  it("routes rgb_image to /rgb8 and the colour upload, with no raster", async () => {
    const gl = fakeGl();
    const out = await loadImagePixels(() => gl, "id1", "rgb_image");
    expect(fetchRgb8).toHaveBeenCalledWith("id1");
    expect(fetchData16).not.toHaveBeenCalled();
    expect(gl.setImageRgb8).toHaveBeenCalledWith(expect.any(Uint8Array), 3, 2);
    // colour channels are colours, not measurements — no probe raster
    expect(out).toEqual({ w: 3, h: 2, raster: null });
  });

  it("routes scalar kinds to /data16 and the packed-16 upload", async () => {
    const gl = fakeGl();
    const out = await loadImagePixels(() => gl, "id2", "spectrum_image", 4);
    expect(fetchData16).toHaveBeenCalledWith("id2", 4);
    expect(gl.setImage16).toHaveBeenCalledWith(raster16.data, 3, 2);
    expect(out?.raster).toBe(raster16);
  });

  it("uploads nothing when the renderer is gone by response time", async () => {
    // the stale-race pin: a late response must not clobber a newer image
    const gl = fakeGl();
    const out = await loadImagePixels(() => null, "id3", "rgb_image");
    expect(out).toBeNull();
    expect(gl.setImageRgb8).not.toHaveBeenCalled();
    const out16 = await loadImagePixels(() => null, "id4", "image");
    expect(out16).toBeNull();
    expect(gl.setImage16).not.toHaveBeenCalled();
  });
});
