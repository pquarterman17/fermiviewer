// Unit test for the grain-segmentation API client (param forwarding,
// incl. the robustness options denoise_sigma + robust).

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { analyzeGrains, analyzeGrainsAsync } from "./api";

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

function lastBody(): Record<string, unknown> {
  const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
    string,
    RequestInit,
  ];
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

describe("analyzeGrains request body", () => {
  it("forwards method, granularity and the robustness options", async () => {
    globalThis.fetch = makeFetch({ n_grains: 3, method: "gradient" });
    await analyzeGrains("img1", {
      method: "gradient",
      roi: [2, 3, 40, 50],
      granularity: 0.08,
      denoise_sigma: 1.5,
      robust: true,
    });
    const body = lastBody();
    expect(body.image_id).toBe("img1");
    expect(body.method).toBe("gradient");
    expect(body.roi).toEqual([2, 3, 40, 50]);
    expect(body.granularity).toBe(0.08);
    expect(body.denoise_sigma).toBe(1.5);
    expect(body.robust).toBe(true);
  });

  it("omits robustness params when not given (server defaults apply)", async () => {
    globalThis.fetch = makeFetch({ n_grains: 2, method: "kmeans" });
    await analyzeGrains("img2", { method: "kmeans", k: 4 });
    const body = lastBody();
    expect(body.method).toBe("kmeans");
    expect(body.k).toBe(4);
    expect("denoise_sigma" in body).toBe(false);
    expect("robust" in body).toBe(false);
  });
});

describe("analyzeGrainsAsync request body", () => {
  it("sets run_async and forwards denoise_sigma", async () => {
    globalThis.fetch = makeFetch({ job_id: "j1" });
    await analyzeGrainsAsync("img3", {
      method: "rag",
      roi: [4, 5, 60, 70],
      merge_threshold: 0.2,
      denoise_sigma: 2,
    });
    const body = lastBody();
    expect(body.run_async).toBe(true);
    expect(body.method).toBe("rag");
    expect(body.roi).toEqual([4, 5, 60, 70]);
    expect(body.merge_threshold).toBe(0.2);
    expect(body.denoise_sigma).toBe(2);
  });
});
