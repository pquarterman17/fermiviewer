import { beforeEach, describe, expect, it } from "vitest";

import { edsSpecies, eelsSpecies } from "../lib/spectrum/species";
import {
  DEFAULT_EDS_SETTINGS,
  edsSettingsOf,
  NO_SPECIES,
  selectedSpeciesOf,
  speciesOf,
  useSpecies,
} from "./species";

const IMG = "img1";
const OTHER = "img2";

beforeEach(() => {
  useSpecies.setState({
    byImage: {},
    selectedByImage: {},
    edsSettingsByImage: {},
  });
});

const list = (id = IMG) => useSpecies.getState().byImage[id] ?? [];

describe("per-image isolation", () => {
  it("keeps each image's list separate and restores it on return", () => {
    // The gap this closes: MapsTab wipes its list on every image change, so
    // switching away and back loses every tick and manual addition.
    const { addSpecies } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    addSpecies(OTHER, edsSpecies("Si", "K", 1.74));

    expect(list(IMG).map((s) => s.symbol)).toEqual(["Fe"]);
    expect(list(OTHER).map((s) => s.symbol)).toEqual(["Si"]);
  });

  it("returns the SAME empty array for an unknown image", () => {
    // A fresh [] here gives useSyncExternalStore a new snapshot every render
    // and re-renders forever — the reason NO_SPECIES exists.
    const { byImage } = useSpecies.getState();
    expect(speciesOf(byImage, "never-opened")).toBe(NO_SPECIES);
    expect(speciesOf(byImage, "never-opened")).toBe(
      speciesOf(byImage, "also-never-opened"),
    );
    expect(speciesOf(byImage, null)).toBe(NO_SPECIES);
  });
});

describe("addSpecies", () => {
  it("refuses a duplicate symbol+transition on the same image", () => {
    // Two rows for one line would cut the same window twice and let the
    // composite take whichever won.
    const { addSpecies } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    expect(list()).toHaveLength(1);
  });

  it("allows the same element on two different transitions", () => {
    // Fe-L2,3 and Fe-K are genuinely different measurements of one element.
    const { addSpecies } = useSpecies.getState();
    addSpecies(IMG, eelsSpecies("Fe", "L2,3", 708));
    addSpecies(IMG, eelsSpecies("Fe", "K", 7112));
    expect(list().map((s) => s.transition)).toEqual(["L2,3", "K"]);
  });

  it("allows the same symbol on two different images", () => {
    const { addSpecies } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    addSpecies(OTHER, edsSpecies("Fe", "K", 6.404));
    expect(list(IMG)).toHaveLength(1);
    expect(list(OTHER)).toHaveLength(1);
  });
});

describe("visibility and removal", () => {
  it("toggles one row without touching its siblings", () => {
    const { addSpecies, setVisible } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    addSpecies(IMG, edsSpecies("Si", "K", 1.74));

    setVisible(IMG, fe.id, false);
    expect(list().find((s) => s.id === fe.id)?.visible).toBe(false);
    expect(list().find((s) => s.symbol === "Si")?.visible).toBe(true);
  });

  it("setAllVisible covers only the named image", () => {
    const { addSpecies, setAllVisible } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    addSpecies(OTHER, edsSpecies("Si", "K", 1.74));

    setAllVisible(IMG, false);
    expect(list(IMG).every((s) => !s.visible)).toBe(true);
    expect(list(OTHER).every((s) => s.visible)).toBe(true);
  });

  it("removes by id, so two rows of one element stay distinguishable", () => {
    const { addSpecies, removeSpecies } = useSpecies.getState();
    const l23 = eelsSpecies("Fe", "L2,3", 708);
    addSpecies(IMG, l23);
    addSpecies(IMG, eelsSpecies("Fe", "K", 7112));

    removeSpecies(IMG, l23.id);
    expect(list().map((s) => s.transition)).toEqual(["K"]);
  });
});

describe("setWindow", () => {
  it("edits the signal window and orders inverted bounds", () => {
    const { addSpecies, setWindow } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);

    setWindow(IMG, fe.id, "signal", { lo: 6.6, hi: 6.2 });
    expect(list()[0].windows.signal).toEqual({ lo: 6.2, hi: 6.6 });
  });

  it("adds an EELS background window without disturbing the signal", () => {
    const { addSpecies, setWindow } = useSpecies.getState();
    const o = eelsSpecies("O", "K", 532);
    addSpecies(IMG, o);

    setWindow(IMG, o.id, "background", { lo: 480, hi: 525 });
    const stored = list()[0];
    expect(stored.windows.background).toEqual({ lo: 480, hi: 525 });
    expect(stored.windows.signal).toEqual({ lo: 532, hi: 582 });
  });

  it("is a no-op for an unknown species id", () => {
    const { addSpecies, setWindow } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    setWindow(IMG, "nope", "signal", { lo: 1, hi: 2 });
    expect(list()[0].windows.signal.lo).toBeCloseTo(6.319, 10);
  });
});

describe("pruneClosed", () => {
  it("drops closed images and keeps open ones", () => {
    // Without this the map grows for the life of the process across an
    // open/close-heavy session — closeImage's teardown cannot reach a store
    // outside the viewer.
    const { addSpecies, pruneClosed } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    addSpecies(OTHER, edsSpecies("Si", "K", 1.74));

    pruneClosed([OTHER]);
    expect(Object.keys(useSpecies.getState().byImage)).toEqual([OTHER]);
  });

  it("clears everything when nothing is open", () => {
    const { addSpecies, pruneClosed } = useSpecies.getState();
    addSpecies(IMG, edsSpecies("Fe", "K", 6.404));
    pruneClosed([]);
    expect(useSpecies.getState().byImage).toEqual({});
  });

  it("also prunes selection and EDS settings for closed images", () => {
    const { addSpecies, selectSpecies, setEdsSettings, pruneClosed } =
      useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    selectSpecies(IMG, fe.id);
    setEdsSettings(IMG, { bg: "bremsstrahlung" });
    addSpecies(OTHER, edsSpecies("Si", "K", 1.74));
    selectSpecies(OTHER, "some-id");

    pruneClosed([OTHER]);
    expect(useSpecies.getState().selectedByImage).toEqual({ [OTHER]: "some-id" });
    expect(useSpecies.getState().edsSettingsByImage).toEqual({});
  });
});

describe("selectSpecies", () => {
  it("selects one species per image, independent of other images", () => {
    const { addSpecies, selectSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    const si = edsSpecies("Si", "K", 1.74);
    addSpecies(IMG, fe);
    addSpecies(OTHER, si);

    selectSpecies(IMG, fe.id);
    selectSpecies(OTHER, si.id);
    expect(useSpecies.getState().selectedByImage).toEqual({
      [IMG]: fe.id,
      [OTHER]: si.id,
    });
  });

  it("resolves through selectedSpeciesOf to the Species object, or null", () => {
    const { addSpecies, selectSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    selectSpecies(IMG, fe.id);

    const state = useSpecies.getState();
    expect(selectedSpeciesOf(state, IMG)).toBe(fe);
    expect(selectedSpeciesOf(state, OTHER)).toBeNull();
    expect(selectedSpeciesOf(state, null)).toBeNull();
  });

  it("falls back to null when removeSpecies drops the selected species", () => {
    // A selection must never be left pointing at a species that is gone.
    const { addSpecies, selectSpecies, removeSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    selectSpecies(IMG, fe.id);

    removeSpecies(IMG, fe.id);
    expect(useSpecies.getState().selectedByImage[IMG]).toBeNull();
  });

  it("leaves an unrelated selection alone when a different species is removed", () => {
    const { addSpecies, selectSpecies, removeSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    const si = edsSpecies("Si", "K", 1.74);
    addSpecies(IMG, fe);
    addSpecies(IMG, si);
    selectSpecies(IMG, fe.id);

    removeSpecies(IMG, si.id);
    expect(useSpecies.getState().selectedByImage[IMG]).toBe(fe.id);
  });

  it("falls back to null when setSpecies replaces the list without the selected id", () => {
    const { addSpecies, selectSpecies, setSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    selectSpecies(IMG, fe.id);

    setSpecies(IMG, [edsSpecies("Si", "K", 1.74)]);
    expect(useSpecies.getState().selectedByImage[IMG]).toBeNull();
  });

  it("survives setSpecies when the replacement list still contains the id", () => {
    const { addSpecies, selectSpecies, setSpecies } = useSpecies.getState();
    const fe = edsSpecies("Fe", "K", 6.404);
    addSpecies(IMG, fe);
    selectSpecies(IMG, fe.id);

    setSpecies(IMG, [fe, edsSpecies("Si", "K", 1.74)]);
    expect(useSpecies.getState().selectedByImage[IMG]).toBe(fe.id);
  });
});

describe("EDS map settings", () => {
  it("returns the stable default snapshot for an image with no stored settings", () => {
    const { edsSettingsByImage } = useSpecies.getState();
    expect(edsSettingsOf(edsSettingsByImage, IMG)).toBe(DEFAULT_EDS_SETTINGS);
    // Same reference across calls — a fresh default object here would
    // re-render a selector's subscriber forever, the NO_SPECIES failure mode.
    expect(edsSettingsOf(edsSettingsByImage, IMG)).toBe(
      edsSettingsOf(edsSettingsByImage, "some-other-never-opened-image"),
    );
    expect(edsSettingsOf(edsSettingsByImage, null)).toBe(DEFAULT_EDS_SETTINGS);
  });

  it("merges a partial update onto the default, keeping the other field", () => {
    const { setEdsSettings } = useSpecies.getState();
    setEdsSettings(IMG, { e0Kev: 15 });
    const settings = edsSettingsOf(useSpecies.getState().edsSettingsByImage, IMG);
    expect(settings).toEqual({ bg: "linear", e0Kev: 15 });
  });

  it("merges a partial update onto the PREVIOUS stored value, not the default", () => {
    const { setEdsSettings } = useSpecies.getState();
    setEdsSettings(IMG, { bg: "bremsstrahlung", e0Kev: 20 });
    setEdsSettings(IMG, { e0Kev: 25 });
    const settings = edsSettingsOf(useSpecies.getState().edsSettingsByImage, IMG);
    expect(settings).toEqual({ bg: "bremsstrahlung", e0Kev: 25 });
  });

  it("keeps settings isolated per image", () => {
    const { setEdsSettings } = useSpecies.getState();
    setEdsSettings(IMG, { bg: "none" });
    const byImage = useSpecies.getState().edsSettingsByImage;
    expect(edsSettingsOf(byImage, IMG)).toEqual({ bg: "none", e0Kev: 30 });
    expect(edsSettingsOf(byImage, OTHER)).toBe(DEFAULT_EDS_SETTINGS);
  });
});
