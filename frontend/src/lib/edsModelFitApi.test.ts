// Unit tests for the EDS model-fit API functions (continuum + peakfit).
// Verify URL + request-body shape (option defaults, snake_case mapping)
// without a live server.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { edsContinuum, edsPeakfit } from "./api";

function makeFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

function sentBody(): Record<string, unknown> {
  const [, init] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
    string,
    RequestInit,
  ];
  return JSON.parse(init.body as string) as Record<string, unknown>;
}

let originalFetch: typeof globalThis.fetch;
beforeEach(() => {
  originalFetch = globalThis.fetch;
});
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.restoreAllMocks();
});

describe("edsContinuum request body", () => {
  it("maps options to snake_case with poisson + fit_absorption defaults", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], continuum: [], amp: 1, absorption: 0,
      reduced_chi2: 1, success: true,
    });
    await edsContinuum("img1", 18, { excludeLines: ["Fe", "Cu"] });
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/continuum");
    const body = sentBody();
    expect(body.image_id).toBe("img1");
    expect(body.e0_kev).toBe(18);
    expect(body.exclude_lines).toEqual(["Fe", "Cu"]);
    expect(body.exclude_windows).toEqual([]);
    expect(body.fit_absorption).toBe(true);
    expect(body.weights).toBe("poisson");
  });

  it("passes weights: null through (uniform)", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], continuum: [], amp: 1, absorption: 0,
      reduced_chi2: 1, success: true,
    });
    await edsContinuum("img1", 20, { weights: null, fitAbsorption: false });
    const body = sentBody();
    expect(body.weights).toBeNull();
    expect(body.fit_absorption).toBe(false);
  });
});

describe("edsPeakfit request body", () => {
  it("defaults background=linear, beam_kv=200, quantify=false", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], model: [], elements: [],
      reduced_chi2: 1, success: true,
    });
    await edsPeakfit("img2", ["Fe", "O"]);
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/peakfit");
    const body = sentBody();
    expect(body.image_id).toBe("img2");
    expect(body.elements).toEqual(["Fe", "O"]);
    expect(body.background).toBe("linear");
    expect(body.beam_kv).toBe(200);
    expect(body.quantify).toBe(false);
    expect(body.e0_kev).toBeNull();
    expect(body.k_factors).toBeNull();
  });

  it("forwards bremsstrahlung background + e0_kev + quantify + k_factors", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], model: [], elements: [],
      reduced_chi2: 1, success: true,
    });
    await edsPeakfit("img2", ["Fe", "Cu"], {
      background: "bremsstrahlung",
      e0Kev: 18,
      quantify: true,
      kFactors: [1, 1.32],
      beamKv: 200,
    });
    const body = sentBody();
    expect(body.background).toBe("bremsstrahlung");
    expect(body.e0_kev).toBe(18);
    expect(body.quantify).toBe(true);
    expect(body.k_factors).toEqual([1, 1.32]);
  });
});
