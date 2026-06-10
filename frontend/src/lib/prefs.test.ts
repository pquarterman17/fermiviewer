// prefs.ts — localStorage persistence incl. the #45 additions
// (auto-contrast percentiles, export scale, inspector grid).

import { describe, expect, it } from "vitest";

import { loadPrefs, savePrefs } from "./prefs";

describe("prefs", () => {
  it("returns full defaults on empty storage", () => {
    expect(loadPrefs()).toEqual({
      defaultCmap: "gray",
      profileWidth: 1,
      minimap: true,
      autoLoPct: 0.5,
      autoHiPct: 99.5,
      exportScale: 1,
      inspectorGrid: 7,
    });
  });

  it("round-trips a save", () => {
    const p = { ...loadPrefs(), autoLoPct: 2, exportScale: 3 };
    savePrefs(p);
    expect(loadPrefs()).toEqual(p);
  });

  it("merges defaults over a PARTIAL stored blob (pre-#45 upgrade path)", () => {
    // a user upgrading from before #45 has only the old three keys
    localStorage.setItem(
      "fv_prefs",
      JSON.stringify({ defaultCmap: "viridis", profileWidth: 5 }),
    );
    const p = loadPrefs();
    expect(p.defaultCmap).toBe("viridis");
    expect(p.profileWidth).toBe(5);
    expect(p.autoLoPct).toBe(0.5); // new keys appear with defaults
    expect(p.inspectorGrid).toBe(7);
  });

  it("corrupted JSON falls back to defaults", () => {
    localStorage.setItem("fv_prefs", "{not json");
    expect(loadPrefs().defaultCmap).toBe("gray");
  });
});
