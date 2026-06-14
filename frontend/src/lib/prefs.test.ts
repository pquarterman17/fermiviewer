// prefs.ts — localStorage persistence + the Preferences-window expansion
// (theme/tools-layout/overlay/export/advanced) with legacy-key backfill.

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { DEFAULTS, loadPrefs, savePrefs } from "./prefs";

describe("prefs", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("returns full defaults on empty storage", () => {
    expect(loadPrefs()).toEqual(DEFAULTS);
  });

  it("round-trips a save", () => {
    const p = { ...DEFAULTS, autoLoPct: 2, exportScale: 3 };
    savePrefs(p);
    expect(loadPrefs()).toEqual(p);
  });

  it("merges defaults over a PARTIAL stored blob (upgrade path)", () => {
    // a user upgrading from before the new keys has only a few set
    localStorage.setItem(
      "fv_prefs",
      JSON.stringify({ defaultCmap: "viridis", profileWidth: 5 }),
    );
    const p = loadPrefs();
    expect(p.defaultCmap).toBe("viridis");
    expect(p.profileWidth).toBe(5);
    expect(p.autoLoPct).toBe(0.5); // pre-existing key default
    expect(p.theme).toBe("system"); // brand-new key default
  });

  it("backfills from legacy single-purpose keys", () => {
    localStorage.setItem("fv_theme", "light");
    localStorage.setItem("fv_tools_layout", "unified");
    localStorage.setItem(
      "fv_overlay",
      JSON.stringify({ color: "#22d3ee", size: "L", endSymbol: "circle" }),
    );
    const p = loadPrefs();
    expect(p.theme).toBe("light");
    expect(p.toolsLayout).toBe("unified");
    expect(p.overlayColor).toBe("#22d3ee");
    expect(p.overlaySize).toBe("L");
    expect(p.overlayEndSymbol).toBe("circle");
  });

  it("explicit fv_prefs value wins over a legacy key", () => {
    localStorage.setItem("fv_theme", "light");
    localStorage.setItem("fv_prefs", JSON.stringify({ theme: "dark" }));
    expect(loadPrefs().theme).toBe("dark");
  });

  it("corrupted JSON falls back to defaults", () => {
    localStorage.setItem("fv_prefs", "{not json");
    expect(loadPrefs().defaultCmap).toBe("gray");
  });
});
