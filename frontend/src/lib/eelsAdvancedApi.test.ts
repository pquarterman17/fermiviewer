// Unit tests for the advanced-EELS API functions (sub-pixel align + RL).
// Verify URL + request-body shape without a live server.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { eelsRichardsonLucy, eelsSubpixelAlign } from "./api";

function makeFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

function call(): { url: string; body: Record<string, unknown> } {
  const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
    string,
    RequestInit,
  ];
  return { url, body: JSON.parse(init.body as string) as Record<string, unknown> };
}

let originalFetch: typeof globalThis.fetch;
beforeEach(() => {
  originalFetch = globalThis.fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("eelsSubpixelAlign", () => {
  it("posts to /eels/subpixel-align with the window", async () => {
    globalThis.fetch = makeFetch({
      aligned: { id: "d1" }, max_shift: 2.3, shifted_fraction: 0.1,
    });
    await eelsSubpixelAlign("img1", [-15, 15]);
    const { url, body } = call();
    expect(url).toBe("/api/eels/subpixel-align");
    expect(body.image_id).toBe("img1");
    expect(body.window).toEqual([-15, 15]);
  });

  it("defaults the window to [-20, 20]", async () => {
    globalThis.fetch = makeFetch({
      aligned: { id: "d1" }, max_shift: 0, shifted_fraction: 0,
    });
    await eelsSubpixelAlign("img1");
    expect(call().body.window).toEqual([-20, 20]);
  });
});

describe("eelsRichardsonLucy", () => {
  it("posts zlp_window + iterations", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], deconvolved: [], iterations: 25,
    });
    await eelsRichardsonLucy("img2", [-4, 4], 25);
    const { url, body } = call();
    expect(url).toBe("/api/eels/richardson-lucy");
    expect(body.image_id).toBe("img2");
    expect(body.zlp_window).toEqual([-4, 4]);
    expect(body.iterations).toBe(25);
  });

  it("defaults zlp_window [-5,5] and 15 iterations", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], deconvolved: [], iterations: 15,
    });
    await eelsRichardsonLucy("img2");
    const { body } = call();
    expect(body.zlp_window).toEqual([-5, 5]);
    expect(body.iterations).toBe(15);
  });
});
