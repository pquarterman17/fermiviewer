import { describe, expect, it } from "vitest";

import { decodeRaster16 } from "./core";

function fakeResponse(headers: Record<string, string>, body: ArrayBuffer): Response {
  return {
    headers: new Headers(headers),
    arrayBuffer: async () => body,
  } as unknown as Response;
}

describe("decodeRaster16", () => {
  it("decodes a zero-length body as an empty (but valid) raster", async () => {
    const raster = await decodeRaster16(
      fakeResponse({ "X-Shape": "0,0", "X-Min": "0", "X-Max": "1" }, new ArrayBuffer(0)),
    );
    expect(raster.w).toBe(0);
    expect(raster.h).toBe(0);
    expect(raster.data.length).toBe(0);
  });

  it("rejects (rather than silently truncating) an odd-length body instead of crashing the caller synchronously", async () => {
    // 3 bytes can't be evenly split into uint16 elements — a malformed
    // encode_raster_u16 response (or a body cut short by a proxy/transfer
    // error). The failure must surface as a REJECTED PROMISE the caller's
    // existing try/catch can handle, not a synchronous throw that could
    // escape an unguarded call site.
    const bad = fakeResponse(
      { "X-Shape": "1,1", "X-Min": "0", "X-Max": "1" },
      new ArrayBuffer(3),
    );
    await expect(decodeRaster16(bad)).rejects.toThrow();
  });

  it("falls back to 0,0 when the shape header is missing entirely", async () => {
    const raster = await decodeRaster16(fakeResponse({}, new ArrayBuffer(0)));
    expect(raster.w).toBe(0);
    expect(raster.h).toBe(0);
    expect(raster.vmin).toBe(0);
    expect(raster.vmax).toBe(1);
    expect(raster.nFrames).toBeNull();
  });
});
