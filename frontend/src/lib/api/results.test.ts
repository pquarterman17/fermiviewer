import { afterEach, describe, expect, it, vi } from "vitest";

import { comparePersistedResults } from "./results";

afterEach(() => vi.unstubAllGlobals());

describe("comparePersistedResults", () => {
  it("omits candidates to request the full compatibility set", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      reference_id: "ref", outputs: [], compatible: [], rejected: [], notes: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await comparePersistedResults("ref");
    expect(fetchMock).toHaveBeenCalledWith("/api/results/compare", expect.objectContaining({
      method: "POST",
      body: JSON.stringify({ reference_id: "ref" }),
    }));
  });

  it("preserves an explicit candidate selection", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      reference_id: "ref", outputs: [], compatible: [], rejected: [], notes: [],
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    await comparePersistedResults("ref", ["b", "a"]);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      reference_id: "ref", candidate_ids: ["b", "a"],
    });
  });
});
