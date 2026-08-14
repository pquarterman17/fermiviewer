// The EDS energy window and the rules that move it (plan items #5 and #6),
// rewired onto the shared species store (Wave 2, SPECTRAL_WORKSPACE_PLAN #11).
//
// The COMMITTED window is no longer local state: it is the selected species'
// `windows.signal`, so a window tuned here is the same window Maps extracts
// with and the same one a re-open of this tab shows. Only the LIVE preview
// during a drag stays local — writing every drag frame to the store would
// make every other subscriber (Maps' live-net column, the map extraction
// hook) recompute on every mouse-move, and the whole point of live/commit is
// that only the commit is expensive.
//
// The anchor a lock re-centres on is `species.energy` — always present once a
// species exists, unlike the old free-floating `lineKev` this hook used to
// track itself. That removes the old "custom window with no element" state
// entirely: every window this hook edits now belongs to a species.

import { useCallback, useEffect, useState } from "react";

import type { Spectrum } from "../../lib/api";
import type { EdsMapBackground } from "../../lib/eds/background";
import type { EnergyWindow, Species } from "../../lib/spectrum/species";
import {
  fitPeakWindow,
  presetWindows,
  type WindowPreset,
} from "../../lib/spectrum/windowPresets";
import { useSpecies } from "../../store/species";

export interface EdsEnergyWindow {
  eLo: number;
  eHi: number;
  locked: boolean;
  setLocked: (locked: boolean) => void;
  /** The line the presets/lock measure from — the selected species' anchor,
   *  or the window's own centre when nothing is selected. */
  anchorKev: number;
  /** Mid-drag frame: move the window without writing the store. */
  live: (lo: number, hi: number) => void;
  /** Commit an edit to the store. Locked, the window is RE-CENTRED on the
   *  species' anchor, so an edge drag widens it symmetrically instead of
   *  walking it off the line. No-ops without an image or a selected species —
   *  there is nothing to write the window onto. */
  commit: (lo: number, hi: number) => void;
  applyPreset: (preset: WindowPreset) => void;
  /** `spectrum` is passed at call time, not held, so this hook has no
   *  dependency on whichever hook resolves the displayed spectrum. */
  applyFit: (spectrum: Spectrum | null) => void;
}

const FALLBACK: EnergyWindow = { lo: 0.5, hi: 1.5 };

export function useEdsEnergyWindow({
  imageId,
  species,
  bgMode,
  recomputeMap,
  onStatus,
}: {
  imageId: string | null;
  /** The species whose window this hook edits, or null when nothing is
   *  selected — every method below no-ops gracefully in that case. */
  species: Species | null;
  bgMode: EdsMapBackground;
  recomputeMap: (lo: number, hi: number, bg: EdsMapBackground) => void;
  onStatus: (message: string) => void;
}): EdsEnergyWindow {
  const setWindow = useSpecies((s) => s.setWindow);
  const [locked, setLocked] = useState(true);
  // Mid-drag preview only. Cleared on every commit AND whenever the selected
  // species changes, so a leftover drag from a previous species (or from
  // before a species existed) never bleeds into the next one's display.
  const [live, setLive] = useState<EnergyWindow | null>(null);

  const speciesId = species?.id ?? null;
  useEffect(() => {
    setLive(null);
  }, [speciesId]);

  const committed = species?.windows.signal ?? null;
  const { lo: eLo, hi: eHi } = live ?? committed ?? FALLBACK;
  const anchorKev = species?.energy ?? (eLo + eHi) / 2;

  const liveFn = useCallback((lo: number, hi: number) => {
    setLive({ lo: Math.min(lo, hi), hi: Math.max(lo, hi) });
  }, []);

  const commit = useCallback(
    (lo: number, hi: number) => {
      if (!imageId || !species) return;
      const half = Math.abs(hi - lo) / 2;
      const window: EnergyWindow = locked
        ? { lo: species.energy - half, hi: species.energy + half }
        : { lo: Math.min(lo, hi), hi: Math.max(lo, hi) };
      setWindow(imageId, species.id, "signal", window);
      setLive(null);
      recomputeMap(window.lo, window.hi, bgMode);
    },
    [imageId, species, locked, bgMode, setWindow, recomputeMap],
  );

  const applyPreset = useCallback(
    (preset: WindowPreset) => {
      const { signal } = presetWindows("eds", anchorKev, preset);
      commit(signal.lo, signal.hi);
    },
    [anchorKev, commit],
  );

  /** Refine on the data: measure the peak's real width and write the window
   *  the fit found DIRECTLY (never re-centred through `commit`'s lock logic —
   *  the whole point is to follow the measured peak, not the tabulated
   *  line). Refuses rather than guessing when there is no resolved peak. */
  const applyFit = useCallback(
    (spectrum: Spectrum | null) => {
      if (!spectrum || !imageId || !species) return;
      const fitted = fitPeakWindow(spectrum.energy, spectrum.counts, anchorKev);
      if (!fitted) {
        onStatus(
          `EDS: no resolved peak near ${anchorKev.toFixed(3)} keV — window unchanged`,
        );
        return;
      }
      const { signal } = fitted.windows;
      setWindow(imageId, species.id, "signal", signal);
      setLive(null);
      recomputeMap(signal.lo, signal.hi, bgMode);
      onStatus(
        `EDS: measured FWHM ${(fitted.fit.fwhm * 1000).toFixed(0)} eV at ` +
          `${fitted.fit.center.toFixed(3)} keV`,
      );
    },
    [anchorKev, bgMode, imageId, species, onStatus, recomputeMap, setWindow],
  );

  return {
    eLo,
    eHi,
    locked,
    setLocked,
    anchorKev,
    live: liveFn,
    commit,
    applyPreset,
    applyFit,
  };
}
