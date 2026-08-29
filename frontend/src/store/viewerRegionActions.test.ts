import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  replaceRegionSets as apiReplaceRegionSets,
  type ProjectRegions,
} from "../lib/api";
import { useViewer } from "./viewer";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  replaceRegionSets: vi.fn(),
}));

const initialState = useViewer.getState();
const next: ProjectRegions = {
  schema: 1,
  classes: [],
  sets: [{ id: "s1", name: "Grains", image_id: "i1", regions: [], meta: {} }],
};

beforeEach(() => {
  useViewer.setState(initialState, true);
  vi.clearAllMocks();
});

describe("replaceRegions", () => {
  it("publishes only the server-accepted workspace", async () => {
    vi.mocked(apiReplaceRegionSets).mockResolvedValue(next);
    await useViewer.getState().replaceRegions(next);
    expect(useViewer.getState().regions).toEqual(next);
    expect(useViewer.getState().status).toBe("updated 1 region set");
  });

  it("keeps the previous workspace when validation fails", async () => {
    const previous: ProjectRegions = { schema: 1, classes: [], sets: [] };
    useViewer.setState({ regions: previous });
    vi.mocked(apiReplaceRegionSets).mockRejectedValue(new Error("invalid ring"));
    await expect(useViewer.getState().replaceRegions(next)).rejects.toThrow("invalid ring");
    expect(useViewer.getState().regions).toBe(previous);
  });
});
