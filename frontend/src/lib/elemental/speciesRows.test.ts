import { beforeEach, describe, expect, it } from "vitest";

import { speciesOf, useSpecies } from "../../store/species";
import { edsSpecies, eelsSpecies } from "../spectrum/species";
import type { EelsEdgeEvidence } from "./eelsIdentify";
import type { Evidence } from "./identify";
import {
  buildRows,
  seedEdsSpeciesFrom,
  seedEelsSpeciesFrom,
  visibleSpecies,
} from "./speciesRows";

beforeEach(() => useSpecies.setState({ byImage: {} }));

function evidence(symbol: string, opts: Partial<Evidence> = {}): Evidence {
  return {
    symbol,
    transition: "K",
    energy: 6.404,
    windowLo: 6.319,
    windowHi: 6.489,
    net: 1000,
    sigma: 30,
    significance: 200,
    confidence: "strong",
    relative: 1,
    recommended: true,
    ...opts,
  };
}

function edgeEvidence(
  symbol: string,
  opts: Partial<EelsEdgeEvidence> = {},
): EelsEdgeEvidence {
  return {
    ...evidence(symbol, { transition: "L23", energy: 708, windowLo: 708, windowHi: 758 }),
    fitWindow: [656, 706],
    ...opts,
  };
}

describe("seedEdsSpeciesFrom", () => {
  it("seeds a fresh image from auto-ID, honouring the above-trace hint", () => {
    const seeded = seedEdsSpeciesFrom(
      [
        evidence("Fe"),
        evidence("Cu", { confidence: "trace", recommended: false }),
      ],
      [],
    );
    expect(seeded?.map((s) => s.symbol)).toEqual(["Fe", "Cu"]);
    expect(seeded?.map((s) => s.visible)).toEqual([true, false]);
  });

  it("refuses to seed over existing decisions", () => {
    // The whole point of separating evidence from decisions: re-identifying
    // refreshes measured numbers without reticking what the user untucked.
    const existing = [edsSpecies("Fe", "K", 6.404, { visible: false })];
    expect(
      seedEdsSpeciesFrom([evidence("Fe"), evidence("Si")], existing),
    ).toBeNull();
  });

  it("anchors each species on the tabulated line", () => {
    const [fe] = seedEdsSpeciesFrom([evidence("Fe")], []) ?? [];
    expect(fe.energy).toBeCloseTo(6.404, 10);
    expect(fe.transition).toBe("K");
  });

  it("keeps auto-ID's own window rather than recomputing a default", () => {
    // The row shows the net counts auto-ID measured; if the species were given
    // a different window, the number on screen would not be the number the map
    // is cut on.
    const wide = evidence("Fe", { windowLo: 6.204, windowHi: 6.604 });
    const [fe] = seedEdsSpeciesFrom([wide], []) ?? [];
    expect(fe.windows.signal.lo).toBeCloseTo(6.204, 10);
    expect(fe.windows.signal.hi).toBeCloseTo(6.604, 10);
  });

  it("seeds an empty list from no evidence rather than returning null", () => {
    // null means "do not touch", [] means "identified nothing" — a caller that
    // conflated them would re-seed on every identify of a blank cube.
    expect(seedEdsSpeciesFrom([], [])).toEqual([]);
  });
});

describe("seedEelsSpeciesFrom", () => {
  it("seeds signal AND background from the evidence's own measured windows", () => {
    // Unlike EDS, the background window matters here too: item 16 auto-places
    // it, and the seeded species must carry the EXACT window auto-assign fit
    // against, not a recomputed default that could disagree with it.
    const [fe] = seedEelsSpeciesFrom([edgeEvidence("Fe")], []) ?? [];
    expect(fe.symbol).toBe("Fe");
    expect(fe.transition).toBe("L23");
    expect(fe.energy).toBe(708);
    expect(fe.windows.signal).toEqual({ lo: 708, hi: 758 });
    expect(fe.windows.background).toEqual({ lo: 656, hi: 706 });
  });

  it("seeds two edges of one element as two species, not a collapsed one", () => {
    // Si K and Si L23 can both be in range at once — seeding must not lose
    // either just because they share a symbol.
    const seeded = seedEelsSpeciesFrom(
      [
        edgeEvidence("Si", { transition: "L23", energy: 99, windowLo: 99, windowHi: 149, fitWindow: [47, 97] }),
        edgeEvidence("Si", { transition: "K", energy: 1839, windowLo: 1839, windowHi: 1889, fitWindow: [1787, 1837] }),
      ],
      [],
    );
    expect(seeded?.map((s) => s.transition)).toEqual(["L23", "K"]);
  });

  it("refuses to seed over existing decisions", () => {
    const existing = [eelsSpecies("Fe", "L23", 708, { visible: false })];
    expect(seedEelsSpeciesFrom([edgeEvidence("Fe")], existing)).toBeNull();
  });

  it("honours the above-trace recommendation the same way EDS does", () => {
    const seeded = seedEelsSpeciesFrom(
      [edgeEvidence("O", { confidence: "trace", recommended: false })],
      [],
    );
    expect(seeded?.[0].visible).toBe(false);
  });
});

describe("buildRows", () => {
  it("builds one row per species, attaching evidence by symbol+transition", () => {
    const species = [edsSpecies("Fe", "K", 6.404), edsSpecies("Si", "K", 1.74)];
    const rows = buildRows(species, [evidence("Fe")]);
    expect(rows).toHaveLength(2);
    expect(rows[0].evidence?.symbol).toBe("Fe");
    expect(rows[1].evidence).toBeNull(); // Si has a row, just nothing measured
  });

  it("drops evidence for a species the user removed", () => {
    // Rows come from species, not evidence — auto-ID still finding Cu must not
    // resurrect a row the user deleted.
    const rows = buildRows([edsSpecies("Fe", "K", 6.404)], [
      evidence("Fe"),
      evidence("Cu"),
    ]);
    expect(rows.map((r) => r.species.symbol)).toEqual(["Fe"]);
  });

  it("preserves species order, not evidence order", () => {
    const species = [edsSpecies("Si", "K", 1.74), edsSpecies("Fe", "K", 6.404)];
    const rows = buildRows(species, [evidence("Fe"), evidence("Si")]);
    expect(rows.map((r) => r.species.symbol)).toEqual(["Si", "Fe"]);
  });

  it("matches evidence to the right edge when one element carries two", () => {
    // Keying by symbol alone would let Si-K's evidence get attached to the
    // Si-L23 row (or vice versa) — the composite key keeps them apart.
    const species = [
      eelsSpecies("Si", "L23", 99),
      eelsSpecies("Si", "K", 1839),
    ];
    const rows = buildRows(species, [
      edgeEvidence("Si", { transition: "L23", net: 500 }),
      edgeEvidence("Si", { transition: "K", net: 9000 }),
    ]);
    expect(rows[0].evidence?.net).toBe(500);
    expect(rows[1].evidence?.net).toBe(9000);
  });
});

describe("the seed-or-restore round trip", () => {
  it("seeds on first visit and restores the user's list on the second", () => {
    // This is item 9's headline behaviour, exercised against the real store:
    // MapsTab used to hold this in component-local state and wipe it on every
    // image change, so ticks and hand-added elements did not survive a switch.
    const { setSpecies, setVisible, pruneClosed } = useSpecies.getState();
    const found = [
      evidence("Fe"),
      evidence("Cu", { confidence: "trace", recommended: false }),
    ];
    const seed = (id: string) => {
      const next = seedEdsSpeciesFrom(found, speciesOf(useSpecies.getState().byImage, id));
      if (next) setSpecies(id, next);
    };

    seed("A");
    const fe = speciesOf(useSpecies.getState().byImage, "A")[0];
    setVisible("A", fe.id, false); // the user unticks iron

    seed("B"); // switching to another cube seeds B independently
    expect(speciesOf(useSpecies.getState().byImage, "B")[0].visible).toBe(true);

    seed("A"); // returning re-identifies, which must NOT retick iron
    const back = speciesOf(useSpecies.getState().byImage, "A");
    expect(back[0].id).toBe(fe.id); // same species, not a rebuilt one
    expect(back[0].visible).toBe(false);

    pruneClosed(["A"]); // closing B drops its list rather than leaking it
    expect(Object.keys(useSpecies.getState().byImage)).toEqual(["A"]);
  });
});

describe("visibleSpecies", () => {
  it("returns only the species that should be mapped", () => {
    const rows = buildRows(
      [
        edsSpecies("Fe", "K", 6.404, { visible: true }),
        edsSpecies("Si", "K", 1.74, { visible: false }),
      ],
      [],
    );
    expect(visibleSpecies(rows).map((s) => s.symbol)).toEqual(["Fe"]);
  });
});
