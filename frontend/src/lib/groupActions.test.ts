import { describe, expect, it } from "vitest";

import { comparableGroupIds, groupPickerLabels } from "./groupActions";

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
});
