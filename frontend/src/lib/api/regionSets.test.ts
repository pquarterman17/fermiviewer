import { afterEach, describe, expect, it, vi } from "vitest";

import { listRegionSets, replaceRegionSets, type ProjectRegions } from "./regionSets";

afterEach(() => vi.unstubAllGlobals());

const regions: ProjectRegions = {
  schema: 1,
  classes: [],
  sets: [{ id: "s1", name: "Grains", image_id: "i1", regions: [], meta: {} }],
};

describe("region workspace API", () => {
  it("lists the live server-carried section", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(regions), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    await expect(listRegionSets()).resolves.toEqual(regions);
    expect(fetchMock).toHaveBeenCalledWith("/api/region-sets");
  });

  it("replaces the complete section atomically", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(regions), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    await replaceRegionSets(regions);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/region-sets/replace",
      expect.objectContaining({ method: "POST", body: JSON.stringify(regions) }),
    );
  });
});
