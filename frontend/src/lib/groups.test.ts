import { describe, expect, it } from "vitest";

import {
  groupMembers,
  resizePanes,
  stepWithin,
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
