import { describe, expect, it } from "vitest";

import type { ImageGroup } from "./groups";
import {
  buildSampleTree,
  entryKey,
  UNGROUPED_SECTION,
  visibleEntries,
} from "./sampleTree";

const images = { a: {}, b: {}, c: {}, d: {} };
const order = ["a", "b", "c", "d"];

const group = (
  id: string,
  ids: string[],
  parent: string | null = null,
): ImageGroup => ({ id, name: id.toUpperCase(), ids, parent });

describe("buildSampleTree", () => {
  it("returns no sections and everything ungrouped for a flat library", () => {
    const tree = buildSampleTree([], images, order);
    expect(tree.roots).toEqual([]);
    expect(tree.ungrouped).toEqual(order);
  });

  it("nests samples under their project and keeps the rest ungrouped", () => {
    const groups = [
      group("proj", []),
      group("s1", ["a", "b"], "proj"),
      group("s2", ["c"], "proj"),
    ];
    const tree = buildSampleTree(groups, images, order);
    expect(tree.roots.map((n) => n.group.id)).toEqual(["proj"]);
    const proj = tree.roots[0];
    expect(proj.depth).toBe(0);
    expect(proj.ids).toEqual([]); // a project holds images through its samples
    expect(proj.children.map((n) => [n.group.id, n.depth, n.ids])).toEqual([
      ["s1", 1, ["a", "b"]],
      ["s2", 1, ["c"]],
    ]);
    expect(tree.ungrouped).toEqual(["d"]);
  });

  it("orders a section's members by library order, not by group order", () => {
    // so a drag-reorder of the library still reorders inside the section
    const tree = buildSampleTree([group("s", ["c", "a"])], images, order);
    expect(tree.roots[0].ids).toEqual(["a", "c"]);
  });

  it("drops closed images from a section", () => {
    const tree = buildSampleTree([group("s", ["a", "gone"])], images, order);
    expect(tree.roots[0].ids).toEqual(["a"]);
  });

  it("renders an image once per group it belongs to", () => {
    const tree = buildSampleTree([group("s1", ["a"]), group("s2", ["a"])], images, order);
    expect(tree.roots.map((n) => n.ids)).toEqual([["a"], ["a"]]);
    expect(tree.ungrouped).not.toContain("a");
  });

  it("cannot hide an image behind a group a root walk never reaches", () => {
    // a cycle (s1 ⇄ s2) is unreachable from the roots — its members must fall
    // back to Ungrouped rather than vanish from the filmstrip
    const groups = [group("s1", ["a"], "s2"), group("s2", ["b"], "s1")];
    const tree = buildSampleTree(groups, images, order);
    expect(tree.roots).toEqual([]);
    expect(tree.ungrouped).toEqual(order);
  });

  it("terminates on a self-parented group", () => {
    const tree = buildSampleTree([group("s", ["a"], "s")], images, order);
    expect(tree.roots).toEqual([]);
    expect(tree.ungrouped).toEqual(order);
  });
});

describe("visibleEntries", () => {
  const groups = [
    group("proj", []),
    group("s1", ["a", "b"], "proj"),
    group("s2", ["c"], "proj"),
  ];
  const tree = buildSampleTree(groups, images, order);

  it("walks sections in DOM order with Ungrouped last", () => {
    expect(visibleEntries(tree, new Set())).toEqual([
      { id: "a", groupId: "s1" },
      { id: "b", groupId: "s1" },
      { id: "c", groupId: "s2" },
      { id: "d", groupId: null },
    ]);
  });

  it("skips a collapsed section's cards", () => {
    expect(visibleEntries(tree, new Set(["s1"])).map((e) => e.id)).toEqual([
      "c",
      "d",
    ]);
  });

  it("skips a collapsed project's whole subtree", () => {
    expect(visibleEntries(tree, new Set(["proj"])).map((e) => e.id)).toEqual(["d"]);
  });

  it("skips the Ungrouped section when it is collapsed", () => {
    const ids = visibleEntries(tree, new Set([UNGROUPED_SECTION])).map((e) => e.id);
    expect(ids).toEqual(["a", "b", "c"]);
  });
});

describe("entryKey", () => {
  it("identifies a card by section AND image, since one image can repeat", () => {
    expect(entryKey({ id: "a", groupId: "s1" })).not.toBe(
      entryKey({ id: "a", groupId: "s2" }),
    );
    expect(entryKey({ id: "a", groupId: null })).toBe(":a");
  });
});
