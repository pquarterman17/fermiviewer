// Unit tests for the EDS model-fit API functions (continuum + peakfit +
// zeta + artifacts). Verify URL + request-body shape (option defaults,
// snake_case mapping) without a live server.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { edsArtifacts, edsContinuum, edsPeakfit, edsRecalibrate, edsZeta } from "./api";

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

describe("edsZeta request body", () => {
  it("defaults dose inputs and forwards zeta_si (#7)", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], model: [], elements: [],
      reduced_chi2: 1, success: true, quant: {},
    });
    await edsZeta("img5", ["Fe", "Cu"], { zetaSi: 1000 });
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/zeta");
    const body = sentBody();
    expect(body.zeta_si).toBe(1000);
    expect(body.zeta_factors).toBeNull();
    expect(body.probe_current_na).toBe(1);
    expect(body.live_time_s).toBe(100);
    expect(body.take_off_angle_deg).toBe(20);
    expect(body.absorption).toBe(true);
    expect(body.density_g_cm3).toBeNull();
    expect(body.remove_artifacts).toBe(false);
  });

  it("forwards explicit zeta_factors, density, and the artifact pre-pass", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], model: [], elements: [],
      reduced_chi2: 1, success: true, quant: {},
    });
    await edsZeta("img5", ["Fe", "Cu"], {
      zetaFactors: [900, 950],
      densityGCm3: 8.5,
      removeArtifacts: true,
      escapeFraction: 0.02,
    });
    const body = sentBody();
    expect(body.zeta_factors).toEqual([900, 950]);
    expect(body.density_g_cm3).toBe(8.5);
    expect(body.remove_artifacts).toBe(true);
    expect(body.escape_fraction).toBe(0.02);
  });
});

describe("edsArtifacts request body", () => {
  it("defaults linear background + 1% escape fraction (#8)", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], artifacts: [], corrected: [],
    });
    await edsArtifacts("img6", ["Fe", "Cu"]);
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/artifacts");
    const body = sentBody();
    expect(body.elements).toEqual(["Fe", "Cu"]);
    expect(body.background).toBe("linear");
    expect(body.escape_fraction).toBe(0.01);
  });
});

describe("edsPeakfit artifact options", () => {
  it("defaults remove_artifacts=false and forwards the toggle (#8)", async () => {
    globalThis.fetch = makeFetch({
      energy: [], spectrum: [], model: [], elements: [],
      reduced_chi2: 1, success: true,
    });
    await edsPeakfit("img2", ["Fe"], { removeArtifacts: true });
    const body = sentBody();
    expect(body.remove_artifacts).toBe(true);
    expect(body.escape_fraction).toBe(0.01);
  });
});

describe("edsRecalibrate request body", () => {
  it("defaults beam_kv=200, search_kev=0.15, apply=true", async () => {
    globalThis.fetch = makeFetch({
      gain: 1, offset: 0, anchors: [], skipped: [], applied: true,
    });
    await edsRecalibrate("img4", { elements: ["Fe", "Cu"] });
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/recalibrate");
    const body = sentBody();
    expect(body.elements).toEqual(["Fe", "Cu"]);
    expect(body.pairs).toEqual([]);
    expect(body.beam_kv).toBe(200);
    expect(body.search_kev).toBe(0.15);
    expect(body.apply).toBe(true);
  });

  it("forwards explicit pairs and apply=false", async () => {
    globalThis.fetch = makeFetch({
      gain: 1, offset: 0, anchors: [], skipped: [], applied: false,
    });
    await edsRecalibrate("img4", { pairs: [[6.39, 6.404]], apply: false });
    const body = sentBody();
    expect(body.pairs).toEqual([[6.39, 6.404]]);
    expect(body.apply).toBe(false);
  });
});
