// Per-image species lists for the Elemental Analysis workspace
// (SPECTRAL_WORKSPACE_PLAN #1).
//
// Keyed by image id rather than cleared on image change, so switching to
// another cube and back restores the list the user built instead of wiping it
// — today `MapsTab` holds its elements in component-local state and discards
// every tick, manual addition and window edit on any image change.
//
// It lives outside the viewer store on purpose: viewer.ts only just graduated
// its 575-line legacy cap down to a plain 500-line module, and per-image maps
// that belong to one workspace do not need to be in the store every surface
// subscribes to. The cost of that choice is that `closeImage`'s teardown
// cannot prune this map for us, which is what `pruneClosed` is for.

import { create } from "zustand";

import type { EdsMapBackground } from "../lib/eds/background";
import type { EnergyWindow, Species } from "../lib/spectrum/species";
import { orderWindow } from "../lib/spectrum/species";

/** Stable empty snapshot. Returning a fresh `[]` from a selector gives
 *  useSyncExternalStore a new reference on every render and re-renders
 *  forever; this is the same module-level constant trick MeasureOverlay uses
 *  for `measures[id] ?? NO_MEASURES`. */
export const NO_SPECIES: readonly Species[] = [];

/** Per-image EDS element-map settings (Wave 1, #11). Same defaults
 *  ElementalWorkshop used to hardcode into every `MapsTab` — moving them
 *  here is what lets a later wave wire Explore's background/beam-energy
 *  controls to the SAME settings Maps extracts with, instead of two
 *  independently-drifting copies. */
export interface EdsMapSettings {
  bg: EdsMapBackground;
  e0Kev: number;
}

/** Stable default snapshot — see NO_SPECIES. `edsSettingsOf` returns this
 *  exact reference for an image with no stored settings, so a selector never
 *  hands out a fresh object on every render. */
export const DEFAULT_EDS_SETTINGS: Readonly<EdsMapSettings> = Object.freeze({
  bg: "linear",
  e0Kev: 30,
});

interface SpeciesState {
  byImage: Record<string, Species[]>;
  /** Replace an image's whole list (auto-ID seeding, reordering). */
  setSpecies: (imageId: string, species: Species[]) => void;
  /** Append, ignoring a symbol+transition already present on that image —
   *  two rows for one line would map the same window twice and colour the
   *  composite from whichever won. */
  addSpecies: (imageId: string, species: Species) => void;
  removeSpecies: (imageId: string, speciesId: string) => void;
  setVisible: (imageId: string, speciesId: string, visible: boolean) => void;
  setAllVisible: (imageId: string, visible: boolean) => void;
  /** Edit one window. Inverted bounds are ordered on the way in, so no
   *  consumer has to sort (item 4 can drag an edge past its partner). */
  setWindow: (
    imageId: string,
    speciesId: string,
    which: "signal" | "background",
    window: EnergyWindow,
  ) => void;
  /** Drop every image not in `openIds`. Must be called from the close/session
   *  teardown; without it this map grows for the life of the process across an
   *  open/close-heavy session. */
  pruneClosed: (openIds: readonly string[]) => void;

  /** The species a row-click framed on an image's spectrum — one at a time,
   *  per image, so switching cubes does not leave a selection pointing at a
   *  species on a different image entirely. Null means "nothing selected". */
  selectedByImage: Record<string, string | null>;
  selectSpecies: (imageId: string, speciesId: string | null) => void;

  /** Per-image EDS map background/beam-energy — see EdsMapSettings. */
  edsSettingsByImage: Record<string, EdsMapSettings>;
  setEdsSettings: (
    imageId: string,
    partial: Partial<EdsMapSettings>,
  ) => void;
}

function mapImage(
  state: SpeciesState,
  imageId: string,
  fn: (list: Species[]) => Species[],
): Pick<SpeciesState, "byImage"> {
  const current = state.byImage[imageId] ?? [];
  return { byImage: { ...state.byImage, [imageId]: fn(current) } };
}

function mapOne(
  list: Species[],
  speciesId: string,
  fn: (s: Species) => Species,
): Species[] {
  return list.map((s) => (s.id === speciesId ? fn(s) : s));
}

/** Drop `imageId`'s selection when it no longer names a species in `list` —
 *  every action that can remove or replace a species must route through
 *  this, so a selection is never left pointing at a species that is gone. */
function dropDanglingSelection(
  state: SpeciesState,
  imageId: string,
  list: Species[],
): Pick<SpeciesState, "selectedByImage"> {
  const selected = state.selectedByImage[imageId];
  if (!selected || list.some((s) => s.id === selected)) {
    return { selectedByImage: state.selectedByImage };
  }
  return {
    selectedByImage: { ...state.selectedByImage, [imageId]: null },
  };
}

export const useSpecies = create<SpeciesState>((set) => ({
  byImage: {},
  selectedByImage: {},
  edsSettingsByImage: {},

  setSpecies: (imageId, species) =>
    set((state) => ({
      byImage: { ...state.byImage, [imageId]: species },
      ...dropDanglingSelection(state, imageId, species),
    })),

  addSpecies: (imageId, species) =>
    set((state) =>
      mapImage(state, imageId, (list) =>
        list.some(
          (s) =>
            s.symbol === species.symbol && s.transition === species.transition,
        )
          ? list
          : [...list, species],
      ),
    ),

  removeSpecies: (imageId, speciesId) =>
    set((state) => {
      const next = mapImage(state, imageId, (list) =>
        list.filter((s) => s.id !== speciesId),
      );
      return {
        ...next,
        ...dropDanglingSelection(state, imageId, next.byImage[imageId]),
      };
    }),

  setVisible: (imageId, speciesId, visible) =>
    set((state) =>
      mapImage(state, imageId, (list) =>
        mapOne(list, speciesId, (s) => ({ ...s, visible })),
      ),
    ),

  setAllVisible: (imageId, visible) =>
    set((state) =>
      mapImage(state, imageId, (list) => list.map((s) => ({ ...s, visible }))),
    ),

  setWindow: (imageId, speciesId, which, window) =>
    set((state) =>
      mapImage(state, imageId, (list) =>
        mapOne(list, speciesId, (s) => ({
          ...s,
          windows: { ...s.windows, [which]: orderWindow(window) },
        })),
      ),
    ),

  pruneClosed: (openIds) =>
    set((state) => {
      const keep = new Set(openIds);
      const byImage: Record<string, Species[]> = {};
      for (const [id, list] of Object.entries(state.byImage)) {
        if (keep.has(id)) byImage[id] = list;
      }
      const selectedByImage: Record<string, string | null> = {};
      for (const [id, selected] of Object.entries(state.selectedByImage)) {
        if (keep.has(id)) selectedByImage[id] = selected;
      }
      const edsSettingsByImage: Record<string, EdsMapSettings> = {};
      for (const [id, settings] of Object.entries(state.edsSettingsByImage)) {
        if (keep.has(id)) edsSettingsByImage[id] = settings;
      }
      return { byImage, selectedByImage, edsSettingsByImage };
    }),

  selectSpecies: (imageId, speciesId) =>
    set((state) => ({
      selectedByImage: { ...state.selectedByImage, [imageId]: speciesId },
    })),

  setEdsSettings: (imageId, partial) =>
    set((state) => ({
      edsSettingsByImage: {
        ...state.edsSettingsByImage,
        [imageId]: {
          ...(state.edsSettingsByImage[imageId] ?? DEFAULT_EDS_SETTINGS),
          ...partial,
        },
      },
    })),
}));

/** The species list for an image, or the stable empty array. Use this rather
 *  than inlining `?? []` at a call site — see NO_SPECIES. */
export function speciesOf(
  byImage: Record<string, Species[]>,
  imageId: string | null,
): readonly Species[] {
  if (!imageId) return NO_SPECIES;
  return byImage[imageId] ?? NO_SPECIES;
}

/** The selected Species for an image, or null — resolved by id rather than
 *  storing the object itself, so a window edit on the selected species (a
 *  new array entry, same id) is still found. Takes the whole store slice
 *  (rather than two separate arguments) so a caller can pass a Zustand
 *  selector straight through: `useSpecies((s) => selectedSpeciesOf(s, id))`.
 *  Never allocates — `.find()` returns the existing array element or
 *  `null`, so this is stable across renders whenever `byImage` is. */
export function selectedSpeciesOf(
  state: Pick<SpeciesState, "byImage" | "selectedByImage">,
  imageId: string | null,
): Species | null {
  if (!imageId) return null;
  const selectedId = state.selectedByImage[imageId];
  if (!selectedId) return null;
  const list = state.byImage[imageId] ?? NO_SPECIES;
  return list.find((s) => s.id === selectedId) ?? null;
}

/** An image's EDS map settings, or the stable default — see
 *  DEFAULT_EDS_SETTINGS. Use this rather than inlining `?? {...}` at a call
 *  site, which would allocate a fresh default object every render. */
export function edsSettingsOf(
  edsSettingsByImage: Record<string, EdsMapSettings>,
  imageId: string | null,
): Readonly<EdsMapSettings> {
  if (!imageId) return DEFAULT_EDS_SETTINGS;
  return edsSettingsByImage[imageId] ?? DEFAULT_EDS_SETTINGS;
}
