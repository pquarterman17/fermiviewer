// The exact raster of ONE region, shown on the stage while a user checks
// what an analysis will read (roadmap item 4, last box). Its own store
// rather than a viewer slice: the state is transient and single-valued, and
// the viewer store sits under the size ratchet.

import { create } from "zustand";

export interface MaskPreview {
  imageId: string;
  /** `"set_id/region_id"` the mask belongs to, so a reselect can tell. */
  regionRef: string;
  /** 1-based inclusive (r1, c1, r2, c2): the box the PNG covers. */
  rect: [number, number, number, number];
  /** `data:image/png;base64,...` — 8-bit grey, 255 inside, 0 outside. */
  href: string;
}

interface RegionPreviewState {
  mask: MaskPreview | null;
  showMask: (mask: MaskPreview) => void;
  /** Clear the shown mask; with a `regionRef`, only if it is that region's,
   *  so a stale cleanup cannot remove a newer selection's mask. */
  clearMask: (regionRef?: string) => void;
}

export const useRegionPreviewStore = create<RegionPreviewState>((set) => ({
  mask: null,
  showMask: (mask) => set({ mask }),
  clearMask: (regionRef) =>
    set((state) =>
      regionRef && state.mask && state.mask.regionRef !== regionRef
        ? state
        : { mask: null },
    ),
}));
