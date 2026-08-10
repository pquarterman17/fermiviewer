import { describe, expect, it } from "vitest";

import {
  GROUP_PALETTE,
  groupAncestors,
  groupChildren,
  groupColor,
  groupMembers,
  normalizeGroupParams,
  pruneGroups,
  resizePanes,
  stepWithin,
  wouldCycle,
  type ComparePane,
  type ImageGroup,
} from "./groups";

const imagesOf = (...ids: string[]): Record<string, true> =>
  Object.fromEntries(ids.map((id) => [id, true]));

const g = (id: string, ids: string[]): ImageGroup => ({ id, name: id, ids });

describe("groupMembers", () => {
  const groups = [g("g1", ["a", "b", "c"])];

  it("returns the group's ids in order when all are still open", () => {
    expect(groupMembers(groups, imagesOf("a", "b", "c"), ["c", "b", "a"], "g1")).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  it("prunes member ids that are no longer open", () => {
    expect(groupMembers(groups, imagesOf("a", "c"), ["a", "b", "c"], "g1")).toEqual([
      "a",
      "c",
    ]);
  });

  it("falls back to the full open order when groupId is null", () => {
    const order = ["x", "y", "z"];
    expect(groupMembers(groups, imagesOf("x", "y", "z"), order, null)).toEqual(order);
  });

  it("falls back to order when the group id is unknown", () => {
    expect(groupMembers(groups, imagesOf("p", "q"), ["p", "q"], "nope")).toEqual([
      "p",
      "q",
    ]);
  });

  it("falls back to order when the group prunes to empty (all members closed)", () => {
    // none of g1's members are open → fall back to the loaded order
    expect(groupMembers(groups, imagesOf("k"), ["k"], "g1")).toEqual(["k"]);
  });

  it("the order fallback itself drops ids not present in images", () => {
    expect(groupMembers([], imagesOf("a"), ["a", "stale"], null)).toEqual(["a"]);
  });
});

describe("sample / project nesting", () => {
  // proj ─┬─ s1 [a, b]
  //       └─ s2 [c]        loose [a] is a second root (no parent key at all)
  const tree: ImageGroup[] = [
    { id: "proj", name: "Project", ids: [], parent: null },
    { id: "s1", name: "S1", ids: ["a", "b"], parent: "proj" },
    { id: "s2", name: "S2", ids: ["c"], parent: "proj" },
    { id: "loose", name: "Loose", ids: ["a"] },
  ];

  describe("groupChildren", () => {
    it("lists the roots for a null parent (absent parent counts as root)", () => {
      expect(groupChildren(tree, null).map((g) => g.id)).toEqual([
        "proj",
        "loose",
      ]);
    });

    it("lists direct children only, in group order", () => {
      expect(groupChildren(tree, "proj").map((g) => g.id)).toEqual(["s1", "s2"]);
    });

    it("is empty for a leaf and for an unknown id", () => {
      expect(groupChildren(tree, "s1")).toEqual([]);
      expect(groupChildren(tree, "nope")).toEqual([]);
    });
  });

  describe("groupAncestors", () => {
    it("walks the chain nearest-parent first", () => {
      const deep: ImageGroup[] = [
        { id: "a", name: "A", ids: [] },
        { id: "b", name: "B", ids: [], parent: "a" },
        { id: "c", name: "C", ids: [], parent: "b" },
      ];
      expect(groupAncestors(deep, "c").map((g) => g.id)).toEqual(["b", "a"]);
    });

    it("is empty for a root and for an unknown id", () => {
      expect(groupAncestors(tree, "proj")).toEqual([]);
      expect(groupAncestors(tree, "loose")).toEqual([]);
      expect(groupAncestors(tree, "nope")).toEqual([]);
    });

    it("stops at a parent that doesn't resolve", () => {
      const orphan: ImageGroup[] = [
        { id: "x", name: "X", ids: [], parent: "ghost" },
      ];
      expect(groupAncestors(orphan, "x")).toEqual([]);
    });

    it("terminates on a cycle instead of hanging", () => {
      const cyclic: ImageGroup[] = [
        { id: "p", name: "P", ids: [], parent: "q" },
        { id: "q", name: "Q", ids: [], parent: "p" },
      ];
      expect(groupAncestors(cyclic, "p").map((g) => g.id)).toEqual(["q"]);
    });
  });

  describe("wouldCycle", () => {
    it("rejects self-parenting", () => {
      expect(wouldCycle(tree, "proj", "proj")).toBe(true);
    });

    it("rejects a parent that is a descendant (direct or deep)", () => {
      expect(wouldCycle(tree, "proj", "s1")).toBe(true);
      const deep: ImageGroup[] = [
        { id: "a", name: "A", ids: [] },
        { id: "b", name: "B", ids: [], parent: "a" },
        { id: "c", name: "C", ids: [], parent: "b" },
      ];
      expect(wouldCycle(deep, "a", "c")).toBe(true); // a is c's grandparent
    });

    it("allows an unrelated parent, a sibling move, and clearing", () => {
      expect(wouldCycle(tree, "loose", "proj")).toBe(false); // becomes a child
      expect(wouldCycle(tree, "s1", "loose")).toBe(false);
      expect(wouldCycle(tree, "s1", null)).toBe(false);
    });

    it("does not treat a dangling parent as a cycle", () => {
      expect(wouldCycle(tree, "s1", "ghost")).toBe(false);
    });

    it("rejects a parent whose own chain is already cyclic", () => {
      const cyclic: ImageGroup[] = [
        { id: "p", name: "P", ids: [], parent: "q" },
        { id: "q", name: "Q", ids: [], parent: "p" },
        { id: "free", name: "Free", ids: [] },
      ];
      expect(wouldCycle(cyclic, "free", "p")).toBe(true);
    });
  });

  describe("groupMembers is untouched by nesting", () => {
    const images = imagesOf("a", "b", "c");

    it("a parent's members are its own ids, never its children's", () => {
      // proj holds no images directly → the null/empty fallback applies, the
      // same as any other empty group (it does NOT roll up s1 + s2)
      expect(groupMembers(tree, images, ["c", "b", "a"], "proj")).toEqual([
        "c",
        "b",
        "a",
      ]);
    });

    it("a nested sample resolves exactly like a flat group", () => {
      expect(groupMembers(tree, images, ["c", "b", "a"], "s1")).toEqual([
        "a",
        "b",
      ]);
    });
  });
});

describe("normalizeGroupParams", () => {
  it("keeps numbers, strings and booleans, defaulting unit to null", () => {
    expect(
      normalizeGroupParams({
        temp: { value: 450, unit: "degC" },
        substrate: { value: "MgO" },
        annealed: { value: true, unit: null },
      }),
    ).toEqual({
      temp: { value: 450, unit: "degC" },
      substrate: { value: "MgO", unit: null },
      annealed: { value: true, unit: null },
    });
  });

  it("drops values JSON can't represent or a plot can't use", () => {
    const dirty = {
      nan: { value: NaN },
      inf: { value: Infinity },
      nested: { value: { a: 1 } },
      missing: { value: undefined },
      "": { value: 1 },
    } as unknown as Parameters<typeof normalizeGroupParams>[0];
    expect(normalizeGroupParams(dirty)).toEqual({});
  });

  it("forces a non-string unit to null and keeps a zero value", () => {
    const p = { bias: { value: 0, unit: 7 } } as unknown as Parameters<
      typeof normalizeGroupParams
    >[0];
    expect(normalizeGroupParams(p)).toEqual({ bias: { value: 0, unit: null } });
  });
});

describe("pruneGroups", () => {
  it("prunes member ids and drops a group left with nothing", () => {
    const groups: ImageGroup[] = [
      { id: "g1", name: "AB", ids: ["a", "gone"] },
      { id: "g2", name: "Gone", ids: ["gone"] },
    ];
    expect(pruneGroups(groups, imagesOf("a"))).toEqual([
      { id: "g1", name: "AB", ids: ["a"] },
    ]);
  });

  it("adds no fields to a legacy group (exact shape preserved)", () => {
    const legacy: ImageGroup[] = [{ id: "g1", name: "AB", ids: ["a", "b"] }];
    expect(pruneGroups(legacy, imagesOf("a", "b"))).toEqual([
      { id: "g1", name: "AB", ids: ["a", "b"] },
    ]);
  });

  it("keeps an image-less project that still has a live descendant", () => {
    const groups: ImageGroup[] = [
      { id: "proj", name: "P", ids: [], parent: null },
      { id: "s1", name: "S1", ids: ["a"], parent: "proj" },
      { id: "s2", name: "S2", ids: ["gone"], parent: "proj" },
    ];
    const out = pruneGroups(groups, imagesOf("a"));
    expect(out.map((g) => g.id)).toEqual(["proj", "s1"]); // s2 died, proj stays
    expect(out[1].parent).toBe("proj");
  });

  it("drops a project whose every sample died", () => {
    const groups: ImageGroup[] = [
      { id: "proj", name: "P", ids: [] },
      { id: "s1", name: "S1", ids: ["gone"], parent: "proj" },
    ];
    expect(pruneGroups(groups, imagesOf("a"))).toEqual([]);
  });

  it("clears a parent that didn't survive rather than dangling", () => {
    // s1 survives on its own members; its parent held no images and has no
    // other live descendant path, so it is dropped and s1 becomes a root
    const groups: ImageGroup[] = [
      { id: "s1", name: "S1", ids: ["a"], parent: "ghost" },
    ];
    expect(pruneGroups(groups, imagesOf("a"))).toEqual([
      { id: "s1", name: "S1", ids: ["a"], parent: null },
    ]);
  });

  it("breaks a cycle that arrives from a file", () => {
    const cyclic: ImageGroup[] = [
      { id: "p", name: "P", ids: ["a"], parent: "q" },
      { id: "q", name: "Q", ids: ["b"], parent: "p" },
    ];
    const out = pruneGroups(cyclic, imagesOf("a", "b"));
    expect(out.map((g) => g.parent ?? null)).toEqual([null, null]);
    expect(groupChildren(out, null)).toHaveLength(2);
  });

  it("carries params and color through untouched", () => {
    const groups: ImageGroup[] = [
      {
        id: "s1",
        name: "S1",
        ids: ["a", "gone"],
        params: { temp: { value: 450, unit: "degC" } },
        color: "#ff8800",
      },
    ];
    expect(pruneGroups(groups, imagesOf("a"))).toEqual([
      {
        id: "s1",
        name: "S1",
        ids: ["a"],
        params: { temp: { value: 450, unit: "degC" } },
        color: "#ff8800",
      },
    ]);
  });
});

describe("stepWithin", () => {
  const m = ["a", "b", "c"];

  it("steps forward with wrap", () => {
    expect(stepWithin(m, "a", 1)).toBe("b");
    expect(stepWithin(m, "c", 1)).toBe("a"); // wrap past the end
  });

  it("steps backward with wrap", () => {
    expect(stepWithin(m, "b", -1)).toBe("a");
    expect(stepWithin(m, "a", -1)).toBe("c"); // wrap past the start
  });

  it("snaps to the first member when current isn't in the list", () => {
    expect(stepWithin(m, "zzz", 1)).toBe("a");
    expect(stepWithin(m, null, -1)).toBe("a");
  });

  it("returns null when there are no members", () => {
    expect(stepWithin([], "a", 1)).toBeNull();
  });
});

describe("resizePanes", () => {
  const panes: ComparePane[] = [
    { imageId: "a", groupId: "g1" },
    { imageId: "b", groupId: null },
  ];

  it("grows, preserving existing panes and appending empty ones", () => {
    const out = resizePanes(panes, 2, 2); // 4 cells
    expect(out).toHaveLength(4);
    expect(out[0]).toEqual({ imageId: "a", groupId: "g1" });
    expect(out[1]).toEqual({ imageId: "b", groupId: null });
    expect(out[2]).toEqual({ imageId: null, groupId: null });
    expect(out[3]).toEqual({ imageId: null, groupId: null });
  });

  it("shrinks, dropping trailing panes", () => {
    const out = resizePanes(panes, 1, 1); // 1 cell
    expect(out).toHaveLength(1);
    expect(out[0]).toEqual({ imageId: "a", groupId: "g1" });
  });

  it("clamps to at least 1×1", () => {
    expect(resizePanes(panes, 0, 0)).toHaveLength(1);
  });
});

describe("groupColor (#29, sample colour tags)", () => {
  it("uses the group's own color when set", () => {
    expect(groupColor({ id: "g1", color: "#123456" })).toBe("#123456");
  });

  it("falls back to a palette pick when color is absent", () => {
    expect(GROUP_PALETTE).toContain(groupColor({ id: "g1" }));
  });

  it("falls back to a palette pick when color is null", () => {
    expect(GROUP_PALETTE).toContain(groupColor({ id: "g1", color: null }));
  });

  it("is deterministic — same id always resolves to the same fallback colour", () => {
    const a = groupColor({ id: "sample-42" });
    const b = groupColor({ id: "sample-42" });
    expect(a).toBe(b);
  });

  it("different ids can resolve to different palette entries", () => {
    const colors = new Set(
      ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"].map((id) =>
        groupColor({ id }),
      ),
    );
    // Not a strict pigeonhole guarantee, but 10 distinct ids over an
    // 8-entry palette should not all collide onto one colour.
    expect(colors.size).toBeGreaterThan(1);
  });
});
