// The EDS energy window and the rules that move it (plan items #5 and #6).
//
// Split out of EdsSpectrumImage rather than added to it: the file was at
// 473/500 and these rules — lock-to-line, width presets, fit-to-measured-peak
// — are exactly the kind of decision that should be pinned by tests rather
// than reachable only by driving a React tree.
//
// The window and its ANCHOR are separate state on purpose, the same split
// `Species.energy` makes: once the window is tuned its midpoint is no longer
// the tabulated line, and re-snapping to a line you no longer remember is
// impossible. `lineKev` is that memory; null means the window is not bound to
// anything and the lock has nothing to offer.

import { useCallback, useState } from "react";

import type { Spectrum } from "../../lib/api";
import {
  fitPeakWindow,
  presetWindows,
  type WindowPreset,
} from "../../lib/spectrum/windowPresets";
import type { EdsMapBackground } from "./useEdsElementMap";

export interface EdsEnergyWindow {
  eLo: number;
  eHi: number;
  /** The line the window is anchored to, or null when it is a free window. */
  lineKev: number | null;
  locked: boolean;
  setLocked: (locked: boolean) => void;
  /** Where the presets read the detector resolution: the anchor if there is
   *  one, else the window's own centre — so presets work on a free window
   *  too, just measured where that window sits. */
  anchorKev: number;
  /** Mid-drag frame: move the window without refetching the element map. */
  live: (lo: number, hi: number) => void;
  /** Commit an edit. Locked to a line, the window is RE-CENTRED on it, so an
   *  edge drag widens it symmetrically instead of walking it off the peak. */
  commit: (lo: number, hi: number) => void;
  /** Bind the window to a newly picked element's line. */
  anchor: (lineKev: number, lo: number, hi: number) => void;
  /** Set an unanchored window (initial default, or a restored pinned region —
   *  "put exactly THIS window back", which a stale anchor would undo). */
  release: (lo: number, hi: number, bg?: EdsMapBackground) => void;
  applyPreset: (preset: WindowPreset) => void;
  /** `spectrum` is passed at call time, not held: the spectrum source hook is
   *  constructed AFTER this one (its onLoaded callback anchors the window), so
   *  taking it as a dependency here would be a cycle. */
  applyFit: (spectrum: Spectrum | null) => void;
}

export function useEdsEnergyWindow({
  bgMode,
  recomputeMap,
  onUnbind,
  onStatus,
}: {
  bgMode: EdsMapBackground;
  recomputeMap: (lo: number, hi: number, bg: EdsMapBackground) => void;
  /** The window stopped following an element's line — the caller drops back
   *  to "(custom)" in its own picker state. */
  onUnbind: () => void;
  onStatus: (message: string) => void;
}): EdsEnergyWindow {
  const [eLo, setELo] = useState(0.5);
  const [eHi, setEHi] = useState(1.5);
  const [lineKev, setLineKev] = useState<number | null>(null);
  const [locked, setLocked] = useState(true);

  const anchorKev = lineKev ?? (eLo + eHi) / 2;

  const live = useCallback((lo: number, hi: number) => {
    setELo(Math.min(lo, hi));
    setEHi(Math.max(lo, hi));
  }, []);

  const commit = useCallback(
    (lo: number, hi: number) => {
      const isLocked = locked && lineKev != null;
      const half = Math.abs(hi - lo) / 2;
      const lo2 = isLocked ? lineKev - half : Math.min(lo, hi);
      const hi2 = isLocked ? lineKev + half : Math.max(lo, hi);
      setELo(lo2);
      setEHi(hi2);
      // Only an UNLOCKED edit unbinds: dropping the element while locked would
      // silently undo the lock the user just asked for.
      if (!isLocked) {
        setLineKev(null);
        onUnbind();
      }
      recomputeMap(lo2, hi2, bgMode);
    },
    [bgMode, lineKev, locked, onUnbind, recomputeMap],
  );

  const anchor = useCallback(
    (kev: number, lo: number, hi: number) => {
      setLineKev(kev);
      setELo(Math.min(lo, hi));
      setEHi(Math.max(lo, hi));
      recomputeMap(Math.min(lo, hi), Math.max(lo, hi), bgMode);
    },
    [bgMode, recomputeMap],
  );

  const release = useCallback(
    (lo: number, hi: number, bg?: EdsMapBackground) => {
      setLineKev(null);
      setELo(Math.min(lo, hi));
      setEHi(Math.max(lo, hi));
      recomputeMap(Math.min(lo, hi), Math.max(lo, hi), bg ?? bgMode);
    },
    [bgMode, recomputeMap],
  );

  const applyPreset = useCallback(
    (preset: WindowPreset) => {
      const { signal } = presetWindows("eds", anchorKev, preset);
      commit(signal.lo, signal.hi);
    },
    [anchorKev, commit],
  );

  /** Refine on the data: measure the peak's real width and fit the window to
   *  it. Refuses rather than guessing when there is no resolved peak — the
   *  window is left exactly as the user had it. */
  const applyFit = useCallback(
    (spectrum: Spectrum | null) => {
    if (!spectrum) return;
    const fitted = fitPeakWindow(spectrum.energy, spectrum.counts, anchorKev);
    if (!fitted) {
      onStatus(
        `EDS: no resolved peak near ${anchorKev.toFixed(3)} keV — window unchanged`,
      );
      return;
    }
    const { signal } = fitted.windows;
    setELo(signal.lo);
    setEHi(signal.hi);
    // The anchor becomes the line AS MEASURED here, so a later locked resize
    // stays on the peak the fit found rather than snapping back to a
    // tabulated energy this spectrum's calibration disagrees with. Re-picking
    // the element restores the tabulated value.
    if (lineKev != null) setLineKev(fitted.fit.center);
    recomputeMap(signal.lo, signal.hi, bgMode);
    onStatus(
      `EDS: measured FWHM ${(fitted.fit.fwhm * 1000).toFixed(0)} eV at ` +
        `${fitted.fit.center.toFixed(3)} keV`,
    );
    },
    [anchorKev, bgMode, lineKev, onStatus, recomputeMap],
  );

  return {
    eLo,
    eHi,
    lineKev,
    locked,
    setLocked,
    anchorKev,
    live,
    commit,
    anchor,
    release,
    applyPreset,
    applyFit,
  };
}
