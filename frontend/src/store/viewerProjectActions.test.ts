// The project store slice (PROJECT_WORKFLOW_PLAN #32–#35).
//
// The assertion that matters most here is the client half of ADR 0002 §4: an
// unavailable image's SAMPLE MEMBERSHIP must survive a load, because the very
// next save serialises `imageGroups` back — a client that pruned the missing
// member would write that loss into the file even though the server kept it.

import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  openProject as apiOpenProject,
  relocateProject as apiRelocateProject,
  saveProject as apiSaveProject,
  type ImageMeta,
  type ProjectLoadResponse,
  type RelocateResponse,
} from "../lib/api";
import { useViewer } from "./viewer";
import { relocateStatus } from "./viewerProjectActions";

vi.mock("../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../lib/api")>()),
  saveProject: vi.fn(),
  openProject: vi.fn(),
  relocateProject: vi.fn(),
}));

const initialState = useViewer.getState();

beforeEach(() => {
  useViewer.setState(initialState, true);
  vi.clearAllMocks();
});

function meta(id: string): ImageMeta {
  return {
    id,
    name: `${id}.tif`,
    kind: "image",
    shape: [4, 4],
    dtype: "uint16",
    pixel_size: 0.5,
    pixel_unit: "nm",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    content_rows: null,
    meta: {},
  };
}

const PROJECT: ProjectLoadResponse["project"] = {
  path: "/p/study.fvp",
  name: "Study",
  payload_mode: "light",
  loaded_payload_mode: "light",
  data_root_hint: "/data",
  primary_param: "anneal_T",
  n_unavailable: 1,
};

/** One resolved image, one missing — a sample holding both. */
const PARTIAL_LOAD: ProjectLoadResponse = {
  images: [meta("here")],
  unavailable: [
    { id: "gone", name: "b.tif", rel: "s2/b.tif", source: "/data/s2/b.tif", size_bytes: 512 },
  ],
  project: PROJECT,
  client_state: {
    order: ["here", "gone"],
    activeId: "here",
    imageGroups: [
      {
        id: "g1",
        name: "Sample A",
        ids: ["here", "gone"],
        params: { anneal_T: { value: 450, unit: "degC" } },
      },
    ],
    measures: {
      gone: [{ id: "m1", kind: "polygon", pts: [{ x: 0.1, y: 0.2 }] }],
    },
  },
};

describe("openProject", () => {
  it("keeps an unavailable image's membership, params and measures", async () => {
    vi.mocked(apiOpenProject).mockResolvedValueOnce(PARTIAL_LOAD);
    await useViewer.getState().openProject("/p/study.fvp");
    const s = useViewer.getState();

    // the placeholder is listed but is NOT a renderable image
    expect(Object.keys(s.unavailable)).toEqual(["gone"]);
    expect(s.unavailable["gone"].rel).toBe("s2/b.tif");
    expect(s.images["gone"]).toBeUndefined();
    expect(s.order).toEqual(["here"]);
    expect(s.activeId).toBe("here");

    // ...and everything hanging off it survived, ready to be re-saved
    expect(s.imageGroups[0].ids).toEqual(["here", "gone"]);
    expect(s.imageGroups[0].params).toEqual({
      anneal_T: { value: 450, unit: "degC" },
    });
    expect(s.measures["gone"]).toHaveLength(1);
    expect(s.currentProject).toEqual({ path: "/p/study.fvp", name: "Study" });
    expect(s.currentWorkspace).toBeNull();
    expect(s.status).toContain("1 unavailable");
  });

  it("keeps pointing at the session's project, not the file just read", async () => {
    // an append load merges a second project's images in; the server answers
    // with the project the SESSION still belongs to, and the store must not
    // repoint itself at the merged file
    vi.mocked(apiOpenProject).mockResolvedValueOnce({
      ...PARTIAL_LOAD,
      project: { ...PROJECT, path: "/p/first.fvp", name: "First" },
    });
    await useViewer.getState().openProject("/p/second.fvp");
    expect(useViewer.getState().currentProject).toEqual({
      path: "/p/first.fvp",
      name: "First",
    });
  });

  it("drops a group whose only members are gone AND unavailable", async () => {
    vi.mocked(apiOpenProject).mockResolvedValueOnce({
      ...PARTIAL_LOAD,
      unavailable: [],
      client_state: {
        ...PARTIAL_LOAD.client_state,
        imageGroups: [{ id: "gDead", name: "closed long ago", ids: ["gone"] }],
      },
    });
    await useViewer.getState().openProject("/p/study.fvp");
    // pruning still happens — it is only the placeholders that are spared
    expect(useViewer.getState().imageGroups).toEqual([]);
  });
});

describe("saveProject", () => {
  it("passes the payload mode through and reports kept references", async () => {
    vi.mocked(apiSaveProject).mockResolvedValue({
      path: "/p/study.fvp",
      payload_mode: "light",
      n_images: 3,
      n_unavailable: 2,
      dropped_samples: 0,
      dropped_measures: 0,
    });
    await useViewer.getState().saveProject("/p/study", "light");
    expect(vi.mocked(apiSaveProject).mock.calls[0][1]).toBe("light");
    expect(useViewer.getState().status).toContain("saved project");
    expect(useViewer.getState().status).toContain("2 unavailable, references kept");
    expect(useViewer.getState().currentProject?.path).toBe("/p/study.fvp");
  });

  it("defaults to light and can be asked for a bundle", async () => {
    vi.mocked(apiSaveProject).mockResolvedValue({
      path: "/p/b.fvp",
      payload_mode: "bundle",
      n_images: 1,
      n_unavailable: 0,
      dropped_samples: 0,
      dropped_measures: 0,
    });
    await useViewer.getState().saveProject("/p/b.fvp");
    expect(vi.mocked(apiSaveProject).mock.calls[0][1]).toBe("light");
    await useViewer.getState().saveProject("/p/b.fvp", "bundle");
    expect(vi.mocked(apiSaveProject).mock.calls[1][1]).toBe("bundle");
    expect(useViewer.getState().status).toContain("saved bundle");
  });

  it("serialises samples and measures for the promoted sections", async () => {
    vi.mocked(apiOpenProject).mockResolvedValueOnce(PARTIAL_LOAD);
    await useViewer.getState().openProject("/p/study.fvp");
    vi.mocked(apiSaveProject).mockResolvedValue({
      path: "/p/study.fvp",
      payload_mode: "light",
      n_images: 2,
      n_unavailable: 1,
      dropped_samples: 0,
      dropped_measures: 0,
    });
    await useViewer.getState().saveProject("/p/study.fvp");

    const sent = vi.mocked(apiSaveProject).mock.calls[0][2];
    // the missing member rides back out — this is the client half of the
    // no-data-loss guarantee
    expect(sent.imageGroups).toEqual([
      {
        id: "g1",
        name: "Sample A",
        ids: ["here", "gone"],
        params: { anneal_T: { value: 450, unit: "degC" } },
      },
    ]);
    expect(sent.measures).toHaveProperty("gone");
  });
});

describe("locateData", () => {
  it("narrows the unavailable list rather than clearing it", async () => {
    vi.mocked(apiOpenProject).mockResolvedValueOnce({
      ...PARTIAL_LOAD,
      unavailable: [
        { id: "a", name: "a.tif", rel: "s1/a.tif", source: null, size_bytes: 1 },
        { id: "b", name: "b.tif", rel: "s2/b.tif", source: null, size_bytes: 2 },
      ],
    });
    await useViewer.getState().openProject("/p/study.fvp");
    expect(Object.keys(useViewer.getState().unavailable)).toEqual(["a", "b"]);

    vi.mocked(apiRelocateProject).mockResolvedValueOnce({
      root: "/moved/s1",
      resolved: [meta("a")],
      still_unavailable: [
        { id: "b", name: "b.tif", rel: "s2/b.tif", source: null, size_bytes: 2 },
      ],
      mismatches: [],
      rejected: [],
    });
    await useViewer.getState().locateData("/moved/s1");
    const s = useViewer.getState();
    // the re-pointed image is a normal library image now...
    expect(s.images["a"]).toBeDefined();
    expect(s.order).toContain("a");
    // ...and the one that moved somewhere else is still waiting for its pick
    expect(Object.keys(s.unavailable)).toEqual(["b"]);
    expect(s.status).toContain("1 still missing");
  });
});

describe("relocateStatus", () => {
  const base: RelocateResponse = {
    root: "/moved",
    resolved: [],
    still_unavailable: [],
    mismatches: [],
    rejected: [],
  };

  it("reports a size mismatch by name instead of hiding it", () => {
    const text = relocateStatus({
      ...base,
      resolved: [meta("a")],
      mismatches: [
        {
          id: "a",
          name: "a.tif",
          rel: "a.tif",
          expected_bytes: 100,
          actual_bytes: 200,
        },
      ],
    });
    expect(text).toContain("located 1 image");
    expect(text).toContain("size differs from the saved project: a.tif");
  });

  it("distinguishes a wrong-data folder from a wrong path", () => {
    expect(
      relocateStatus({
        ...base,
        still_unavailable: [
          { id: "a", name: "a.tif", rel: "a.tif", source: null, size_bytes: 1 },
        ],
        rejected: [{ id: "a", name: "a.tif" }],
      }),
    ).toContain("1 found but not matching");
  });
});
