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

  it("copyIncludesAnnotations defaults to true and round-trips", () => {
    expect(loadPrefs().copyIncludesAnnotations).toBe(true);
    savePrefs({ ...DEFAULTS, copyIncludesAnnotations: false });
    expect(loadPrefs().copyIncludesAnnotations).toBe(false);
  });

  it("lassoSimplifyPx semantic migration: an old-semantics stored value is ignored, not backfilled (pref rename)", () => {
    // lassoSimplifyPx changed meaning (capture spacing -> close-time
    // epsilon) with the rename to lassoCloseSimplifyPx; a stored value
    // under the OLD key is deliberately NOT carried over — using it as the
    // new field's value would silently apply an old-semantics number as a
    // destructive simplification epsilon. Mutation-verified against the
    // PRE-fix source (field still named lassoSimplifyPx): there this
    // assertion reads `p.lassoSimplifyPx` unchanged at 20 — the RENAME
    // itself (and its accompanying non-migration) is the fix, so RED here
    // means "loadPrefs().lassoCloseSimplifyPx doesn't even exist yet /
    // isn't 2"; after the rename with no legacyBackfill entry added for
    // the old key, the stored 20 lands on an unused property and
    // lassoCloseSimplifyPx falls through to its own default, GREEN.
    localStorage.setItem(
      "fv_prefs",
      JSON.stringify({ lassoSimplifyPx: 20 }),
    );
    const p = loadPrefs();
    expect(p.lassoCloseSimplifyPx).toBe(2);
  });

  it("a legacy stored blob missing the copy-annotations key resolves to true", () => {
    // simulates a prefs blob saved before this preference existed — it must
    // NOT come back undefined/falsy, or Copy Image would silently go bare
    localStorage.setItem(
      "fv_prefs",
      JSON.stringify({ defaultCmap: "viridis" }),
    );
    expect(loadPrefs().copyIncludesAnnotations).toBe(true);
  });
});
