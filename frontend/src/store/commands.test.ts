import { beforeEach, describe, expect, it, vi } from "vitest";

import { mergeCommands, useCommands, type Action } from "./commands";

const act = (id: string, label: string, group = "G"): Action => ({
  id,
  group,
  label,
  run: vi.fn(),
});

describe("mergeCommands", () => {
  it("keeps all curated actions and appends menu-only ones", () => {
    const curated = [act("c1", "Fit image", "View")];
    const menu = [act("m1", "Defect Count", "Analyze")];
    const merged = mergeCommands(curated, menu);
    expect(merged.map((a) => a.label)).toEqual(["Fit image", "Defect Count"]);
  });

  it("drops a menu command duplicating a curated label (case-insensitive)", () => {
    const curated = [act("c1", "Keyboard shortcuts", "Help")];
    const menu = [
      act("m1", "Keyboard Shortcuts", "Help"), // dup of curated → dropped
      act("m2", "Back Project (FBP)…", "Analyze"),
    ];
    const merged = mergeCommands(curated, menu);
    expect(merged).toHaveLength(2);
    expect(merged[0].id).toBe("c1"); // curated wins
    expect(merged[1].label).toBe("Back Project (FBP)…");
  });

  it("is a no-op append when there are no menu commands", () => {
    const curated = [act("c1", "Fit image")];
    expect(mergeCommands(curated, [])).toEqual(curated);
  });
});

describe("useCommands store", () => {
  beforeEach(() => useCommands.setState({ menuCommands: [] }));

  it("setMenuCommands replaces the published list", () => {
    const cmds = [act("m1", "Roughness", "Analyze")];
    useCommands.getState().setMenuCommands(cmds);
    expect(useCommands.getState().menuCommands).toEqual(cmds);
  });
});
