// Unit test for the cross-section layers API client.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyzeLayers, analyzeLayersMulti, editLayers } from "./api";

function makeFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

let originalFetch: typeof globalThis.fetch;
beforeEach(() => {
  originalFetch = globalThis.fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("analyzeLayers request body", () => {
  it("defaults axis=auto, sensitivity=0.3, n_layers=0, reduce=mean", async () => {
    globalThis.fetch = makeFetch({
      axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.9,
      pixel_size: 1, unit: "px", depth_pos: [], depth_profile: [],
      interfaces: [], layers: [],
    });
    await analyzeLayers("img1");
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/analyze/layers");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.image_id).toBe("img1");
    expect(body.axis).toBe("auto");
    expect(body.sensitivity).toBe(0.3);
    expect(body.n_layers).toBe(0);
    expect(body.reduce).toBe("mean");
    expect(body.destripe).toBe(false);
    expect(body.roi).toBeNull();
  });

  it("forwards de-curtain options (median reduce + destripe)", async () => {
    globalThis.fetch = makeFetch({
      axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.9,
      pixel_size: 1, unit: "px", depth_pos: [], depth_profile: [],
      interfaces: [], layers: [],
    });
    await analyzeLayers("img4", { reduce: "median", destripe: true });
    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.reduce).toBe("median");
    expect(body.destripe).toBe(true);
  });

  it("forwards roi, axis, sensitivity and n_layers", async () => {
    globalThis.fetch = makeFetch({
      axis: "x", layers_horizontal: false, tilt_deg: 0, coherence: 0.8,
      pixel_size: 1, unit: "px", depth_pos: [], depth_profile: [],
      interfaces: [], layers: [],
    });
    await analyzeLayers("img2", { roi: [1, 1, 50, 50], axis: "x", sensitivity: 0.5, nLayers: 4 });
    const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.roi).toEqual([1, 1, 50, 50]);
    expect(body.axis).toBe("x");
    expect(body.sensitivity).toBe(0.5);
    expect(body.n_layers).toBe(4);
  });
});

describe("editLayers request body", () => {
  it("posts positions + axis to the edit endpoint", async () => {
    globalThis.fetch = makeFetch({
      axis: "y", layers_horizontal: true, tilt_deg: 0, coherence: 0.9,
      pixel_size: 1, unit: "px", depth_pos: [], depth_profile: [],
      interfaces: [], layers: [],
    });
    await editLayers("img3", [30, 90], {
      roi: [11, 21, 100, 200],
      axis: "y", waviness: true, reduce: "median", destripe: true,
    });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/analyze/layers/edit");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.positions).toEqual([30, 90]);
    expect(body.roi).toEqual([11, 21, 100, 200]);
    expect(body.axis).toBe("y");
    expect(body.waviness).toBe(true);
    expect(body.reduce).toBe("median");
    expect(body.destripe).toBe(true);
  });
});

describe("analyzeLayersMulti request body", () => {
  it("posts image_ids + reference to the multi endpoint", async () => {
    globalThis.fetch = makeFetch({
      axis: "y", unit: "nm", reference_positions: [], maps: [],
    });
    await analyzeLayersMulti(["a", "b", "c"], { reference: 1 });
    const [url, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(url).toBe("/api/analyze/layers/multi");
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.image_ids).toEqual(["a", "b", "c"]);
    expect(body.reference).toBe(1);
    expect(body.waviness).toBe(true);
  });
});
