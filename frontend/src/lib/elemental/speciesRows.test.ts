import { beforeEach, describe, expect, it } from "vitest";

import { speciesOf, useSpecies } from "../../store/species";
import { edsSpecies } from "../spectrum/species";
import type { IdentifiedElement } from "./identify";
import { buildRows, seedSpeciesFrom, visibleSpecies } from "./speciesRows";

beforeEach(() => useSpecies.setState({ byImage: {} }));

function evidence(
  symbol: string,
  opts: Partial<IdentifiedElement> = {},
): IdentifiedElement {
  return {
    symbol,
    line: "K",
    energyKev: 6.404,
    eLo: 6.319,
    eHi: 6.489,
    net: 1000,
    sigma: 30,
    significance: 200,
    confidence: "strong",
    deltaKev: 0.001,
    relative: 1,
    recommended: true,
    ...opts,
  };
}

describe("seedSpeciesFrom", () => {
  it("seeds a fresh image from auto-ID, honouring the above-trace hint", () => {
    const seeded = seedSpeciesFrom(
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
    expect(seedSpeciesFrom([evidence("Fe"), evidence("Si")], existing)).toBeNull();
  });

  it("anchors each species on the tabulated line", () => {
    const [fe] = seedSpeciesFrom([evidence("Fe")], []) ?? [];
    expect(fe.energy).toBeCloseTo(6.404, 10);
    expect(fe.transition).toBe("K");
  });

  it("keeps auto-ID's own window rather than recomputing a default", () => {
    // The row shows the net counts auto-ID measured; if the species were given
    // a different window, the number on screen would not be the number the map
    // is cut on.
    const wide = evidence("Fe", { eLo: 6.204, eHi: 6.604 });
    const [fe] = seedSpeciesFrom([wide], []) ?? [];
    expect(fe.windows.signal.lo).toBeCloseTo(6.204, 10);
    expect(fe.windows.signal.hi).toBeCloseTo(6.604, 10);
  });

  it("seeds an empty list from no evidence rather than returning null", () => {
    // null means "do not touch", [] means "identified nothing" — a caller that
    // conflated them would re-seed on every identify of a blank cube.
    expect(seedSpeciesFrom([], [])).toEqual([]);
  });
});

describe("buildRows", () => {
  it("builds one row per species, attaching evidence by symbol", () => {
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
      const next = seedSpeciesFrom(found, speciesOf(useSpecies.getState().byImage, id));
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
