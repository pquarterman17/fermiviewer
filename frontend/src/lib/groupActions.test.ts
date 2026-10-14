import { describe, expect, it } from "vitest";

import {
  comparableGroupIds,
  groupPickerLabels,
  groupsContaining,
  nextGroupName,
  sideBySidePair,
} from "./groupActions";

describe("group actions", () => {
  it("labels repeated group names so each maps to one group", () => {
    expect(
      groupPickerLabels([
        { id: "1", name: "A", ids: [] },
        { id: "2", name: "B", ids: [] },
        { id: "3", name: "A", ids: [] },
      ]),
    ).toEqual(["A", "B", "A (2)"]);
  });

  it("compares only groups with an open image", () => {
    expect(
      comparableGroupIds(
        [
          { id: "g1", name: "A", ids: ["x"] },
          { id: "g2", name: "B", ids: ["gone"] },
          { id: "g3", name: "C", ids: ["y", "gone"] },
        ],
        { x: {}, y: {} },
      ),
    ).toEqual(["g1", "g3"]);
  });

  it("labels nested samples with their project path", () => {
    expect(
      groupPickerLabels([
        { id: "p1", name: "Run 1", ids: [] },
        { id: "p2", name: "Run 2", ids: [] },
        { id: "s1", name: "Sample", ids: [], parent: "p1" },
        { id: "s2", name: "Sample", ids: [], parent: "p2" },
      ]),
    ).toEqual(["Run 1", "Run 2", "Run 1 / Sample", "Run 2 / Sample"]);
  });

  it("suggests the first unused Group N name", () => {
    expect(nextGroupName([])).toBe("Group 1");
    expect(
      nextGroupName([
        { id: "a", name: "Group 1", ids: [] },
        { id: "b", name: "Group 3", ids: [] },
      ]),
    ).toBe("Group 2");
  });

  it("pairs at most two groups, preferring the selection's", () => {
    const groups = [
      { id: "g1", name: "A", ids: ["a"] },
      { id: "g2", name: "B", ids: ["b"] },
      { id: "g3", name: "C", ids: ["c"] },
    ];
    const images = { a: {}, b: {}, c: {} };
    expect(sideBySidePair(groups, images, [])).toEqual(["g1", "g2"]);
    expect(sideBySidePair(groups, images, ["c"])).toEqual(["g3", "g1"]);
    expect(sideBySidePair(groups, images, ["b", "c"])).toEqual(["g2", "g3"]);
    expect(sideBySidePair(groups.slice(0, 1), images, [])).toEqual(["g1"]);
  });

  it("finds the groups an image belongs to", () => {
    const groups = [
      { id: "g1", name: "A", ids: ["a", "b"] },
      { id: "g2", name: "B", ids: ["b"] },
      { id: "g3", name: "C", ids: ["c"] },
    ];
    expect(groupsContaining(groups, ["b"]).map((g) => g.id)).toEqual(["g1", "g2"]);
    expect(groupsContaining(groups, ["z"])).toEqual([]);
  });
});
