import { describe, expect, it } from "vitest";

import { edsSpecies, eelsSpecies } from "../spectrum/species";
import type { Species } from "../spectrum/species";
import { conflictsFor, detectWindowConflicts } from "./windowConflicts";

describe("detectWindowConflicts", () => {
  it("fires BOTH overlap and unresolved for Ta M / Si K at default windows", () => {
    // The gate case, by the numbers: 1.710 and 1.740 keV are 30 eV apart —
    // well inside the ~79 eV detector FWHM at that energy — and their
    // default +-85 eV windows ([1.625, 1.795] / [1.655, 1.825]) also overlap.
    const ta = edsSpecies("Ta", "M", 1.710);
    const si = edsSpecies("Si", "K", 1.740);
    const conflicts = detectWindowConflicts([ta, si]);
    const kinds = conflicts.map((c) => c.kind).sort();
    expect(kinds).toEqual(["overlap", "unresolved"]);
    for (const c of conflicts) {
      expect([c.aId, c.bId].sort()).toEqual([ta.id, si.id].sort());
    }
  });

  it("reports no conflict for a well-separated EDS pair", () => {
    // Ta L (8.146) instead of Ta M — the companion case to the one above:
    // if this test used a fixed eV constant instead of fanoFwhmKev(mid), it
    // would fail to distinguish it from the overlapping pair (see the R2
    // mutation test below).
    const ta = edsSpecies("Ta", "L", 8.146);
    const si = edsSpecies("Si", "K", 1.740);
    expect(detectWindowConflicts([ta, si])).toEqual([]);
  });

  it("keeps 'unresolved' after the windows are narrowed to EXACTLY touching", () => {
    // Detector physics does not care where the windows are: narrowing Ta M
    // and Si K until their windows just meet at 1.725 keV clears the
    // "overlap" conflict but the lines are still 30 eV apart. Windows are
    // set explicitly (not via halfWindowKev) so the touching boundary is
    // bit-exact rather than one float epsilon off it either way.
    const ta: Species = {
      ...edsSpecies("Ta", "M", 1.710),
      windows: { signal: { lo: 1.695, hi: 1.725 } },
    };
    const si: Species = {
      ...edsSpecies("Si", "K", 1.740),
      windows: { signal: { lo: 1.725, hi: 1.755 } },
    };
    const conflicts = detectWindowConflicts([ta, si]);
    expect(conflicts.map((c) => c.kind)).toEqual(["unresolved"]);
  });

  it("flags an EELS background window that runs through another edge's onset", () => {
    const background: Species = {
      ...eelsSpecies("Ti", "L23", 456, { widthEv: 50 }),
      windows: { signal: { lo: 1000, hi: 1050 }, background: { lo: 430, hi: 480 } },
    };
    // The edge's window has been dragged away from its own onset (630-680),
    // so ONLY the stored anchor (456) sits inside the background window --
    // window-vs-window alone would miss this, which is the point: the
    // background is still fit through the true edge threshold energy no
    // matter where the user later moved that edge's own signal window.
    const edge: Species = {
      ...eelsSpecies("O", "K", 456),
      windows: { signal: { lo: 630, hi: 680 } },
    };
    const conflicts = detectWindowConflicts([background, edge]);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].kind).toBe("background");

    // moving the background window below the onset clears it
    const cleared: Species = {
      ...background,
      windows: { ...background.windows, background: { lo: 370, hi: 420 } },
    };
    expect(detectWindowConflicts([cleared, edge])).toEqual([]);
  });

  it("ignores a hidden species entirely", () => {
    const ta = edsSpecies("Ta", "M", 1.710, { visible: false });
    const si = edsSpecies("Si", "K", 1.740);
    expect(detectWindowConflicts([ta, si])).toEqual([]);
  });

  it("orders each pair aId < bId and never reports a self-pair", () => {
    const ta = edsSpecies("Ta", "M", 1.710);
    const si = edsSpecies("Si", "K", 1.740);
    const forward = detectWindowConflicts([ta, si]);
    const reversed = detectWindowConflicts([si, ta]);
    expect(forward.length).toBeGreaterThan(0);
    for (const c of forward) {
      expect(c.aId < c.bId).toBe(true);
      expect(c.aId).not.toBe(c.bId);
    }
    // the pair's (aId, bId) must not depend on which one was passed first —
    // a species-id ordering keyed on call order would put ta/si one way
    // round with [ta, si] and the other way round with [si, ta].
    expect(reversed).toEqual(forward);
  });
});

describe("conflictsFor", () => {
  it("finds a species' conflicts from either end of the pair", () => {
    const ta = edsSpecies("Ta", "M", 1.710);
    const si = edsSpecies("Si", "K", 1.740);
    const conflicts = detectWindowConflicts([ta, si]);
    expect(conflictsFor(conflicts, ta.id)).toHaveLength(conflicts.length);
    expect(conflictsFor(conflicts, si.id)).toHaveLength(conflicts.length);
  });

  it("returns nothing for a species with no conflicts", () => {
    const ta = edsSpecies("Ta", "L", 8.146);
    const si = edsSpecies("Si", "K", 1.740);
    const conflicts = detectWindowConflicts([ta, si]);
    expect(conflictsFor(conflicts, ta.id)).toEqual([]);
  });
});
