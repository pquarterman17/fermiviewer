// Unit tests for the EDS SI explorer API functions added to api.ts.
// These test the *client-side shape logic* (URL construction, NaN
// serialisation, option defaults) without hitting a live server.

import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

// ── helpers ────────────────────────────────────────────────────────────

function makeFetch(body: unknown, status = 200) {
  return vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: status === 200 ? "OK" : "Error",
    json: async () => body,
    text: async () => JSON.stringify(body),
  });
}

// ── edsLineEnergy ─────────────────────────────────────────────────────

describe("edsLineEnergy URL construction", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("calls /api/eds/line-energy/{symbol} with no query by default", async () => {
    const body = { symbol: "Fe", line: "K", energy_kev: 6.404 };
    globalThis.fetch = makeFetch(body);
    const { edsLineEnergy } = await import("./api");
    const r = await edsLineEnergy("Fe");
    expect(globalThis.fetch).toHaveBeenCalledOnce();
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toBe("/api/eds/line-energy/Fe");
    expect(r.energy_kev).toBe(6.404);
  });

  it("appends beam_kv query param when provided", async () => {
    const body = { symbol: "Fe", line: "K", energy_kev: 6.404 };
    globalThis.fetch = makeFetch(body);
    const { edsLineEnergy } = await import("./api");
    await edsLineEnergy("Fe", 200);
    const [url] = (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [string];
    expect(url).toContain("beam_kv=200");
  });
});

// ── edsElementMap ─────────────────────────────────────────────────────

describe("edsElementMap request body", () => {
  let originalFetch: typeof globalThis.fetch;

  beforeEach(() => {
    originalFetch = globalThis.fetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("sends correct default options", async () => {
    const body = {
      map: [[1, 2], [3, 4]],
      shape: [2, 2],
      e_lo: 1.0,
      e_hi: 2.0,
      bg: "linear",
      total_counts: 10,
      map_meta: null,
    };
    globalThis.fetch = makeFetch(body);
    const { edsElementMap } = await import("./api");
    const r = await edsElementMap("img1", 1.0, 2.0);
    const [, init] =
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
        string,
        RequestInit,
      ];
    const sent = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sent["image_id"]).toBe("img1");
    expect(sent["e_lo"]).toBe(1.0);
    expect(sent["e_hi"]).toBe(2.0);
    expect(sent["bg"]).toBe("linear");          // default
    expect(sent["save_derived"]).toBe(false);   // default
    expect(r.map_meta).toBeNull();
  });

  it("passes saveDerived=true as save_derived in body", async () => {
    const body = {
      map: [[5]],
      shape: [1, 1],
      e_lo: 6.3,
      e_hi: 6.5,
      bg: "none",
      total_counts: 5,
      map_meta: { id: "derived-1", kind: "image" },
    };
    globalThis.fetch = makeFetch(body);
    const { edsElementMap } = await import("./api");
    await edsElementMap("img2", 6.3, 6.5, { bg: "none", saveDerived: true });
    const [, init] =
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
        string,
        RequestInit,
      ];
    const sent = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sent["bg"]).toBe("none");
    expect(sent["save_derived"]).toBe(true);
  });

  it("forwards bremsstrahlung bg + e0_kev", async () => {
    const body = {
      map: [[1]], shape: [1, 1], e_lo: 6.3, e_hi: 6.5,
      bg: "bremsstrahlung", total_counts: 1, map_meta: null,
    };
    globalThis.fetch = makeFetch(body);
    const { edsElementMap } = await import("./api");
    await edsElementMap("img3", 6.3, 6.5, { bg: "bremsstrahlung", e0Kev: 18 });
    const [, init] =
      (globalThis.fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
        string,
        RequestInit,
      ];
    const sent = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(sent["bg"]).toBe("bremsstrahlung");
    expect(sent["e0_kev"]).toBe(18);
  });
});
