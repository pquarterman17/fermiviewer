import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listRegionSets as apiListRegionSets,
  replaceRegionSets as apiReplaceRegionSets,
  type ProjectRegions,
} from "../lib/api";
import { useViewer } from "./viewer";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  listRegionSets: vi.fn(),
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
  useViewer.setState({ regionsLoaded: true, regionsLoadError: null });
  vi.clearAllMocks();
});

describe("replaceRegions", () => {
  it("hydrates server-carried regions without writing them back", () => {
    useViewer.setState({ regionsLoaded: false });
    useViewer.getState().hydrateRegions(next);
    expect(useViewer.getState().regions).toEqual(next);
    expect(useViewer.getState().regionsLoaded).toBe(true);
    expect(apiReplaceRegionSets).not.toHaveBeenCalled();
  });

  it("fails closed when the initial baseline has not loaded", async () => {
    useViewer.setState({ regionsLoaded: false });
    await expect(useViewer.getState().replaceRegions(next)).rejects.toThrow(
      "analysis regions are not loaded",
    );
    expect(apiReplaceRegionSets).not.toHaveBeenCalled();
  });

  it("surfaces hydration failure and succeeds on retry", async () => {
    vi.mocked(apiListRegionSets).mockRejectedValueOnce(new Error("offline"));
    await expect(useViewer.getState().refreshRegions()).rejects.toThrow("offline");
    expect(useViewer.getState()).toMatchObject({
      regionsLoaded: false,
      regionsLoadError: "offline",
    });

    vi.mocked(apiListRegionSets).mockResolvedValueOnce(next);
    await useViewer.getState().refreshRegions();
    expect(useViewer.getState()).toMatchObject({
      regions: next,
      regionsLoaded: true,
      regionsLoadError: null,
    });
  });

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

  it("tracks selection and visibility without mutating geometry", () => {
    useViewer.getState().selectRegion("s1", "r1");
    useViewer.getState().toggleRegionSetVisibility("s1");
    useViewer.getState().toggleRegionVisibility("s1", "r1");
    expect(useViewer.getState().regionUi).toEqual({
      selectedSetId: "s1",
      selectedRegionId: "r1",
      hiddenSetIds: ["s1"],
      hiddenRegionKeys: ['["s1","r1"]'],
    });
    expect(apiReplaceRegionSets).not.toHaveBeenCalled();
  });
});
