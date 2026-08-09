// Global physical-scale lock for browsing a series at constant on-screen
// size (plan item 7 — PROJECT_WORKFLOW_PLAN.md). Standalone store, same
// shape as store/stage.ts: kept OUT of store/viewer.ts, which is pinned
// at 575 lines with zero headroom.
//
// The lock is GLOBAL, not per-group (gate G5, resolved 2026-08-09): the
// jarring rescale this feature removes happens while stepping through
// whatever is loaded, including across sample boundaries, so a per-group
// lock would just move the jump to every group edge instead.
//
// `scale` is in the active image's own `pixel_unit` per screen px (see
// lib/geometry.ts physicalScale for the unit convention) — this store
// does not know or care which unit that is; callers label it.
//
// No UI wiring lives here — Stage/Compare consuming this lock via
// lib/geometry.ts's resolveScaleView is a separate plan item (8/9).

import { create } from "zustand";

interface BrowseScaleState {
  locked: boolean;
  scale: number | null;
  /** Turns the lock on and seeds it from the given scale (e.g. the
   *  active image's current physicalScale at the moment of enabling). */
  enable: (scale: number) => void;
  /** Updates the locked scale value without changing whether the lock is
   *  on (double-click-to-fit re-seeds rather than silently disabling). */
  reseed: (scale: number) => void;
  /** Turns the lock off and drops the seeded scale. */
  clear: () => void;
}

export const useBrowseScale = create<BrowseScaleState>((set) => ({
  locked: false,
  scale: null,
  enable: (scale) => set({ locked: true, scale }),
  reseed: (scale) => set({ scale }),
  clear: () => set({ locked: false, scale: null }),
}));
