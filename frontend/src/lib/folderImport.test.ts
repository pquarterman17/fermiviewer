// folderImport.ts (PROJECT_WORKFLOW_PLAN.md items 2-3): the seeding rules
// are pure and tested here without touching fetch; only the last describe
// block exercises the async orchestrator, mocking just the network call
// and driving the real store (same pattern as rename.test.ts).

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("./api/folders", () => ({
  openFolders: vi.fn(),
}));

import type { FourDMeta, ImageMeta } from "./api/core";
import { openFolders, type FolderGroupResult } from "./api/folders";
import { useFolderImportNotice } from "../store/folderImportNotice";
import { useViewer } from "../store/viewer";
import {
  dedupeGroupName,
  importFolders,
  mergedGroupName,
  seedGroupSpecs,
  seedProjectSpecs,
  summarizeImport,
  type FolderRootInfo,
} from "./folderImport";

function img(id: string): ImageMeta {
  return {
    id,
    name: `${id}.tif`,
    kind: "image",
    shape: [8, 8],
    dtype: "float64",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  } as ImageMeta;
}

function fourd(id: string): FourDMeta {
  return {
    id,
    name: `${id}.mib`,
    is_fourd: true,
    source: null,
    scan_shape: [4, 4],
    det_shape: [4, 4],
    dtype: "uint16",
    scan_axes: [],
    det_axes: [],
    nav_available: false,
  n_frames: 0,
  scan_shape_from_file: true,
  scan_shape_options: [],
  };
}

const group = (name: string, ids: string[]): FolderGroupResult => ({
  name,
  images: ids.map(img),
});

describe("dedupeGroupName", () => {
  it.each<[string, string, string[], string]>([
    ["no collision returns the name unchanged", "400C", [], "400C"],
    ["a taken name gets ' (2)'", "400C", ["400C"], "400C (2)"],
    [
      "a doubly-taken name skips to ' (3)'",
      "400C",
      ["400C", "400C (2)"],
      "400C (3)",
    ],
  ])("%s", (_desc, name, taken, expected) => {
    expect(dedupeGroupName(name, new Set(taken))).toBe(expected);
  });
});

describe("mergedGroupName", () => {
  it("joins folder names with '+' when there are few", () => {
    expect(mergedGroupName([group("400C", ["a"]), group("500C", ["b"])])).toBe(
      "400C + 500C",
    );
  });

  it("truncates to '+ N more' beyond the named cap", () => {
    const groups = ["a", "b", "c", "d", "e"].map((n) => group(n, ["x"]));
    expect(mergedGroupName(groups)).toBe("a + b + c + 2 more");
  });
});

describe("seedGroupSpecs", () => {
  it("one folder selected -> one group", () => {
    const { specs, emptyFolders } = seedGroupSpecs([group("400C", ["a", "b"])], false);
    expect(specs).toEqual([{ name: "400C", images: [img("a"), img("b")] }]);
    expect(emptyFolders).toEqual([]);
  });

  it("N folders -> N groups, each named after its folder", () => {
    const { specs } = seedGroupSpecs(
      [group("400C", ["a"]), group("500C", ["b"]), group("600C", ["c"])],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["400C", "500C", "600C"]);
    expect(specs.map((s) => s.images.map((m) => m.id))).toEqual([["a"], ["b"], ["c"]]);
  });

  it("merge checkbox -> exactly one group containing every image", () => {
    const { specs } = seedGroupSpecs(
      [group("400C", ["a", "b"]), group("500C", ["c"])],
      true,
    );
    expect(specs).toHaveLength(1);
    expect(specs[0].images.map((m) => m.id)).toEqual(["a", "b", "c"]);
    expect(specs[0].name).toBe("400C + 500C");
  });

  it("name collisions get a numeric suffix rather than silently merging", () => {
    const { specs } = seedGroupSpecs(
      [group("data", ["a"]), group("data", ["b"])],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["data", "data (2)"]);
    // each group keeps its own images — never combined under one name
    expect(specs[0].images.map((m) => m.id)).toEqual(["a"]);
    expect(specs[1].images.map((m) => m.id)).toEqual(["b"]);
  });

  it("a folder that yielded no supported images produces no empty group, and is reported", () => {
    const { specs, emptyFolders } = seedGroupSpecs(
      [group("400C", ["a"]), group("empty", [])],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["400C"]);
    expect(emptyFolders).toEqual(["empty"]);
  });

  it("merge mode still drops empty folders from the merged image set and reports them", () => {
    const { specs, emptyFolders } = seedGroupSpecs(
      [group("400C", ["a"]), group("empty", [])],
      true,
    );
    expect(specs).toHaveLength(1);
    expect(specs[0].images.map((m) => m.id)).toEqual(["a"]);
    expect(emptyFolders).toEqual(["empty"]);
  });

  it("every folder empty -> no groups at all, all reported", () => {
    const { specs, emptyFolders } = seedGroupSpecs(
      [group("empty1", []), group("empty2", [])],
      false,
    );
    expect(specs).toEqual([]);
    expect(emptyFolders).toEqual(["empty1", "empty2"]);
  });
});

describe("seedProjectSpecs", () => {
  const root = (name: string, groupCount: number): FolderRootInfo => ({
    name,
    groupCount,
  });

  it("a flat folder (one root, one group) produces no project", () => {
    const { specs, projects } = seedProjectSpecs(
      [group("400C", ["a"])],
      [root("400C", 1)],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["400C"]);
    expect(projects).toEqual([]);
  });

  it("a folder of folders (one root, N groups) gets a parent project", () => {
    const { specs, projects } = seedProjectSpecs(
      [group("sampleA", ["a"]), group("sampleB", ["b"])],
      [root("StudyA", 2)],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["sampleA", "sampleB"]);
    expect(projects).toEqual([
      { name: "StudyA", childNames: ["sampleA", "sampleB"] },
    ]);
  });

  it("multiple selected dirs: each root is judged independently", () => {
    const { projects } = seedProjectSpecs(
      [
        group("flat", ["a"]),
        group("sub1", ["b"]),
        group("sub2", ["c"]),
      ],
      [root("flat", 1), root("nested", 2)],
      false,
    );
    expect(projects).toEqual([{ name: "nested", childNames: ["sub1", "sub2"] }]);
  });

  it("a root's own loose-image child collides with the project name — the project is renamed, not the child", () => {
    // StudyA has loose images (named "StudyA" per seedGroupSpecs) AND
    // subfolders — 3 groups from one root.
    const { specs, projects } = seedProjectSpecs(
      [group("StudyA", ["a"]), group("sub1", ["b"]), group("sub2", ["c"])],
      [root("StudyA", 3)],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["StudyA", "sub1", "sub2"]);
    expect(projects).toEqual([
      { name: "StudyA (2)", childNames: ["StudyA", "sub1", "sub2"] },
    ]);
  });

  it("merge mode never nests, even with root info present", () => {
    const { projects } = seedProjectSpecs(
      [group("sampleA", ["a"]), group("sampleB", ["b"])],
      [root("StudyA", 2)],
      true,
    );
    expect(projects).toEqual([]);
  });

  it("no root info at all -> no projects (backward compatible with a plain scan)", () => {
    const { projects } = seedProjectSpecs(
      [group("sampleA", ["a"]), group("sampleB", ["b"])],
      [],
      false,
    );
    expect(projects).toEqual([]);
  });

  it("a folder of folders where all but one child turned out empty is flat, not a project", () => {
    const { specs, projects, emptyFolders } = seedProjectSpecs(
      [group("sampleA", ["a"]), group("sampleB", [])],
      [root("StudyA", 2)],
      false,
    );
    expect(specs.map((s) => s.name)).toEqual(["sampleA"]);
    expect(emptyFolders).toEqual(["sampleB"]);
    expect(projects).toEqual([]);
  });
});

describe("summarizeImport", () => {
  it.each<[string, Parameters<typeof summarizeImport>[0], string]>([
    [
      "plain success, no notes",
      { groupCount: 2, imageCount: 40, skipped: 0, truncated: false, emptyFolders: [] },
      "opened 40 images in 2 groups",
    ],
    [
      "singular image/group phrasing",
      { groupCount: 1, imageCount: 1, skipped: 0, truncated: false, emptyFolders: [] },
      "opened 1 image in 1 group",
    ],
    [
      "skipped files noted",
      { groupCount: 2, imageCount: 40, skipped: 3, truncated: false, emptyFolders: [] },
      "opened 40 images in 2 groups — skipped 3 unsupported",
    ],
    [
      "truncated noted",
      { groupCount: 1, imageCount: 500, skipped: 0, truncated: true, emptyFolders: [] },
      "opened 500 images in 1 group — truncated at 500 files",
    ],
    [
      "empty folders noted",
      { groupCount: 1, imageCount: 5, skipped: 0, truncated: false, emptyFolders: ["blanks"] },
      "opened 5 images in 1 group — no supported images in blanks",
    ],
    [
      "all notes combine in order",
      {
        groupCount: 2,
        imageCount: 40,
        skipped: 3,
        truncated: true,
        emptyFolders: ["blanks"],
      },
      "opened 40 images in 2 groups — skipped 3 unsupported; truncated at 500 files; no supported images in blanks",
    ],
  ])("%s", (_desc, summary, expected) => {
    expect(summarizeImport(summary)).toBe(expected);
  });
});

// ── async orchestration ─────────────────────────────────────────────────

const initialState = useViewer.getState();

describe("importFolders", () => {
  beforeEach(() => {
    useViewer.setState(initialState, true);
    useFolderImportNotice.getState().clear();
    vi.clearAllMocks();
  });

  it("ingests images and creates one group per folder by default", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("400C", ["a", "b"]), group("500C", ["c"])],
      skipped: 0,
      truncated: false,
    });

    await importFolders(["/data/study"]);

    const s = useViewer.getState();
    expect(Object.keys(s.images).sort()).toEqual(["a", "b", "c"]);
    expect(s.imageGroups.map((g) => g.name)).toEqual(["400C", "500C"]);
    expect(s.imageGroups.map((g) => g.ids)).toEqual([["a", "b"], ["c"]]);
    expect(s.status).toBe("opened 3 images in 2 groups");
  });

  it("merges every folder into one group when asked", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("400C", ["a"]), group("500C", ["b"])],
      skipped: 2,
      truncated: false,
    });

    await importFolders(["/data/400C", "/data/500C"], { merge: true });

    const s = useViewer.getState();
    expect(s.imageGroups).toHaveLength(1);
    expect(s.imageGroups[0].ids).toEqual(["a", "b"]);
    expect(s.status).toBe("opened 2 images in 1 group — skipped 2 unsupported");
  });

  it("drops FourDMeta entries from the group (no render pipeline yet) and reports an all-4D folder as empty", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("mixed", ["a"]), { name: "stem", images: [fourd("d1")] }],
      skipped: 0,
      truncated: false,
    });

    await importFolders(["/data/study"]);

    const s = useViewer.getState();
    expect(Object.keys(s.images)).toEqual(["a"]);
    expect(s.imageGroups.map((g) => g.name)).toEqual(["mixed"]);
    expect(s.status).toBe(
      "opened 1 image in 1 group — no supported images in stem",
    );
  });

  it("does nothing when no paths are given", async () => {
    await importFolders([]);
    expect(openFolders).not.toHaveBeenCalled();
  });

  it("returns null (rather than a summary) when no paths are given", async () => {
    expect(await importFolders([])).toBeNull();
  });

  it("returns the import summary", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("400C", ["a"])],
      skipped: 0,
      truncated: false,
      roots: [],
    });

    const result = await importFolders(["/data/study"]);
    expect(result).toEqual({
      groupCount: 1,
      imageCount: 1,
      skipped: 0,
      truncated: false,
      emptyFolders: [],
    });
  });

  it("also reports through the persistent folder-import notice (item 5)", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("400C", ["a"])],
      skipped: 1,
      truncated: false,
      roots: [],
    });

    await importFolders(["/data/study"]);

    expect(useFolderImportNotice.getState().result).toEqual({
      groupCount: 1,
      imageCount: 1,
      skipped: 1,
      truncated: false,
      emptyFolders: [],
    });
  });

  it("a folder of folders (item 27) nests the sample groups under a new parent project", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("sampleA", ["a"]), group("sampleB", ["b"])],
      skipped: 0,
      truncated: false,
      roots: [{ name: "StudyA", group_count: 2 }],
    });

    await importFolders(["/data/StudyA"]);

    const s = useViewer.getState();
    const byName = (n: string) => s.imageGroups.find((g) => g.name === n)!;
    const project = byName("StudyA");
    expect(project.ids).toEqual([]); // a project holds images only via children
    expect(byName("sampleA").parent).toBe(project.id);
    expect(byName("sampleB").parent).toBe(project.id);
  });

  it("a flat folder (item 27's unchanged simple case) creates no parent project", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [group("400C", ["a", "b"])],
      skipped: 0,
      truncated: false,
      roots: [{ name: "400C", group_count: 1 }],
    });

    await importFolders(["/data/400C"]);

    const s = useViewer.getState();
    expect(s.imageGroups).toHaveLength(1);
    expect(s.imageGroups[0].name).toBe("400C");
    expect(s.imageGroups[0].parent).toBeUndefined();
  });

  it("multiple selected dirs: only the folder-of-folders one gets a project", async () => {
    vi.mocked(openFolders).mockResolvedValue({
      groups: [
        group("flat", ["a"]),
        group("sub1", ["b"]),
        group("sub2", ["c"]),
      ],
      skipped: 0,
      truncated: false,
      roots: [
        { name: "flat", group_count: 1 },
        { name: "nested", group_count: 2 },
      ],
    });

    await importFolders(["/data/flat", "/data/nested"]);

    const s = useViewer.getState();
    const byName = (n: string) => s.imageGroups.find((g) => g.name === n)!;
    expect(byName("flat").parent).toBeUndefined();
    const project = byName("nested");
    expect(project.ids).toEqual([]);
    expect(byName("sub1").parent).toBe(project.id);
    expect(byName("sub2").parent).toBe(project.id);
  });
});
