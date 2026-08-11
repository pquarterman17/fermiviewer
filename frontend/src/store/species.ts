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

import type { EnergyWindow, Species } from "../lib/spectrum/species";
import { orderWindow } from "../lib/spectrum/species";

/** Stable empty snapshot. Returning a fresh `[]` from a selector gives
 *  useSyncExternalStore a new reference on every render and re-renders
 *  forever; this is the same module-level constant trick MeasureOverlay uses
 *  for `measures[id] ?? NO_MEASURES`. */
export const NO_SPECIES: readonly Species[] = [];

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

export const useSpecies = create<SpeciesState>((set) => ({
  byImage: {},

  setSpecies: (imageId, species) =>
    set((state) => ({ byImage: { ...state.byImage, [imageId]: species } })),

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
    set((state) =>
      mapImage(state, imageId, (list) => list.filter((s) => s.id !== speciesId)),
    ),

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
      return { byImage };
    }),
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
