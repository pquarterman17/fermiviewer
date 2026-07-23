import { useEffect, useMemo, useState } from "react";

import {
  edsAutoAssign,
  edsLines,
  type EdsAutoAssignResult,
  type EdsLine,
} from "../lib/api";
import { buildPeakMarkers, type PeakMarker } from "../lib/eds/peakMarkers";

/**
 * Peak-label markers for the EDS spectrum: auto-detected peaks (matched to
 * K/L/M lines, once per image) merged with the currently selected element's
 * lines. Returns [] when disabled. Fetch failures resolve to no markers — a
 * missing label must never surface an error on the spectrum.
 */
export function useEdsPeakMarkers(
  imageId: string | null,
  selectedSymbol: string | null, // "(custom)"/null → no selected lines
  energy: number[] | null, // full spectrum energy axis (keV)
  enabled: boolean,
): PeakMarker[] {
  const [auto, setAuto] = useState<EdsAutoAssignResult | null>(null);
  const [selected, setSelected] = useState<EdsLine[]>([]);
  const energyLo = energy && energy.length ? energy[0] : null;
  const energyHi = energy && energy.length ? energy[energy.length - 1] : null;

  // auto-detect peaks once per image (independent of the selected element)
  useEffect(() => {
    if (!enabled || !imageId) {
      setAuto(null);
      return;
    }
    let live = true;
    edsAutoAssign(imageId)
      .then((r) => {
        if (live) setAuto(r);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [enabled, imageId]);

  // the selected element's lines over the visible energy range
  useEffect(() => {
    if (
      !enabled ||
      !selectedSymbol ||
      selectedSymbol === "(custom)" ||
      energyLo == null ||
      energyHi == null
    ) {
      setSelected([]);
      return;
    }
    let live = true;
    edsLines(energyLo, energyHi, [selectedSymbol])
      .then((ls) => {
        if (live) setSelected(ls);
      })
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [enabled, selectedSymbol, energyLo, energyHi]);

  return useMemo(
    () => (enabled ? buildPeakMarkers(selected, auto) : []),
    [enabled, selected, auto],
  );
}
