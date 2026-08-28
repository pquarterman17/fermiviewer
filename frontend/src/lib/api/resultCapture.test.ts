// The client half of the item-1 profile / diffraction-indexing adopters:
// `record` is opt-in, and when it is off the request body must be BYTE-FOR-
// BYTE what it was before capture existed. That is the property worth
// pinning — measure-as-you-go drags fire these endpoints continuously, and
// a stray `record: false` reaching a route whose model defaults it to false
// would be harmless today but would silently become a capture the moment
// anyone flipped the default.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { measurePolyline, measureProfile } from "./core";
import { diffractionIndex } from "./diffraction-export";

type Sent = { url: string; body: Record<string, unknown> };

const sent: Sent[] = [];

function stubFetch(payload: unknown): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string, init?: RequestInit) => {
      sent.push({
        url: String(url),
        body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown>,
      });
      return {
        ok: true,
        status: 200,
        headers: new Headers({ "Content-Type": "application/json" }),
        json: async () => payload,
        text: async () => JSON.stringify(payload),
      } as unknown as Response;
    }),
  );
}

const PROFILE_BODY = {
  dist: [0, 1],
  intensity: [1, 2],
  length: 1,
  unit: "nm",
  reduce: "mean",
};

const INDEX_BODY = { center: [10, 10], measured_r: [5], candidates: [] };

beforeEach(() => {
  sent.length = 0;
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("record is opt-in on the capture-capable endpoints", () => {
  it("omits `record` entirely from a two-point profile by default", async () => {
    stubFetch(PROFILE_BODY);
    await measureProfile("img-1", { x: 0, y: 0 }, { x: 4, y: 4 });
    expect(sent[0].url).toBe("/api/measure/profile");
    expect("record" in sent[0].body).toBe(false);
  });

  it("omits `record` entirely from a polyline profile by default", async () => {
    stubFetch(PROFILE_BODY);
    await measurePolyline("img-1", [
      { x: 0, y: 0 },
      { x: 4, y: 4 },
    ]);
    expect("record" in sent[0].body).toBe(false);
  });

  it("omits `record` entirely from a diffraction index by default", async () => {
    stubFetch(INDEX_BODY);
    await diffractionIndex("img-1", [[10, 12]]);
    expect(sent[0].url).toBe("/api/diffraction/index");
    expect("record" in sent[0].body).toBe(false);
  });

  it("sends record:true on a two-point profile when asked, keeping the 1-based (row, col) conversion", async () => {
    stubFetch({ ...PROFILE_BODY, result: { id: "r1", created_at: "t" } });
    const res = await measureProfile(
      "img-1",
      { x: 0, y: 0 },
      { x: 4, y: 4 },
      3,
      null,
      "mean",
      true,
    );
    expect(sent[0].body.record).toBe(true);
    // 0-based (x, y) in, 1-based (row, col) out — unchanged by capture
    expect(sent[0].body.a).toEqual([1, 1]);
    expect(sent[0].body.b).toEqual([5, 5]);
    expect(res.result?.id).toBe("r1");
  });

  it("sends record:true on a polyline profile when asked", async () => {
    stubFetch({ ...PROFILE_BODY, result: { id: "r2", created_at: "t" } });
    const res = await measurePolyline(
      "img-1",
      [
        { x: 0, y: 0 },
        { x: 4, y: 4 },
      ],
      1,
      "mean",
      true,
    );
    expect(sent[0].body.record).toBe(true);
    expect(sent[0].body.points).toEqual([
      [1, 1],
      [5, 5],
    ]);
    expect(res.result?.id).toBe("r2");
  });

  it("sends record:true on a diffraction index when asked, alongside the existing options", async () => {
    stubFetch({ ...INDEX_BODY, result: { id: "r3", created_at: "t" } });
    const res = await diffractionIndex("img-1", [[10, 12]], {
      cameraLengthMm: 200,
      tolerance: 0.1,
      topN: 9,
      record: true,
    });
    expect(sent[0].body.record).toBe(true);
    expect(sent[0].body.camera_length_mm).toBe(200);
    expect(sent[0].body.tolerance).toBe(0.1);
    expect(sent[0].body.top_n).toBe(9);
    expect(res.result?.id).toBe("r3");
  });

  it("treats an explicit false the same as absent, so the off path has one wire shape", async () => {
    stubFetch(INDEX_BODY);
    await diffractionIndex("img-1", [[10, 12]], { record: false });
    expect("record" in sent[0].body).toBe(false);
  });
});
