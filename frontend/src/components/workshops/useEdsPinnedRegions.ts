// Pinned integration regions for the EDS Spectrum-Image explorer — split
// out of EdsSpectrumImage.tsx (2026-08-14, at 480/500 lines).
//
// Owns the region list's whole lifecycle: pinning the live integration,
// clearing on cube change (new pixels — the previous integrations don't
// describe them), and restore. Restoring a pinned region puts its window
// back and frames it, so the number in the table and the peak on screen
// are the same measurement. The background model travels with it too — a
// region pinned under "none" must not silently re-render under whatever
// background happens to be active. Species-aware (task #11 Wave 2): a
// region names the species it was measured on, so restoring re-selects
// (or, if the user removed it since, re-creates) that species rather than
// mutating a "custom" free window.

import { useEffect, useState } from "react";

import type { WindowIntegration } from "../../lib/eds/integrate";
import {
  makeRegion,
  upsertRegion,
  type IntegrationRegion,
} from "../../lib/spectrum/regions";
import { edsSpecies, type Species } from "../../lib/spectrum/species";
import { frameWindow, type XRange } from "../../lib/spectrum/zoomRange";
import { speciesOf, useSpecies } from "../../store/species";

/** A region with no recorded transition (an older pin, or one restored
 *  without one) is re-created on the commonest EDS shell — better than
 *  leaving the species unlabelled, and correctable from Maps afterward. */
const FALLBACK_TRANSITION = "K";

interface UseEdsPinnedRegionsOpts {
  imageId: string | null;
  /** Live integration of the current window; null when there is nothing
   *  to pin (nothing selected, or no spectrum yet). */
  integration: WindowIntegration | null;
  selected: Species | null;
  /** Label of the spectrum the integration was measured on. */
  sourceLabel: string;
  /** Full energy extent + narrowest span, for framing a restored window. */
  bounds: XRange;
  minSpan: number;
  /** Zoom the plot to the given range (the explorer's setXRange; null
   *  when frameWindow declines to produce one). */
  onFrame: (range: XRange | null) => void;
}

export function useEdsPinnedRegions({
  imageId,
  integration,
  selected,
  sourceLabel,
  bounds,
  minSpan,
  onFrame,
}: UseEdsPinnedRegionsOpts) {
  const [regions, setRegions] = useState<IntegrationRegion[]>([]);

  const selectSpeciesStore = useSpecies((s) => s.selectSpecies);
  const addSpeciesStore = useSpecies((s) => s.addSpecies);
  const setWindowStore = useSpecies((s) => s.setWindow);
  const setEdsSettingsStore = useSpecies((s) => s.setEdsSettings);

  // A new cube brings new pixels: the previous integrations don't describe it.
  useEffect(() => {
    setRegions([]);
  }, [imageId]);

  const addRegion = () => {
    if (!integration || !selected) return;
    setRegions((prev) =>
      upsertRegion(
        prev,
        makeRegion(integration, selected.symbol, sourceLabel, selected.transition),
      ),
    );
  };

  const restoreRegion = (region: IntegrationRegion) => {
    if (!imageId) return;
    setEdsSettingsStore(imageId, { bg: region.bg });
    onFrame(frameWindow(region.eLo, region.eHi, bounds, minSpan));
    if (!region.symbol) return;

    const list = speciesOf(useSpecies.getState().byImage, imageId);
    let target = list.find(
      (s) =>
        s.symbol === region.symbol &&
        (!region.transition || s.transition === region.transition),
    );
    if (!target) {
      target = edsSpecies(
        region.symbol,
        region.transition ?? FALLBACK_TRANSITION,
        (region.eLo + region.eHi) / 2,
        { halfWindowKev: (region.eHi - region.eLo) / 2 },
      );
      addSpeciesStore(imageId, target);
    }
    selectSpeciesStore(imageId, target.id);
    setWindowStore(imageId, target.id, "signal", {
      lo: region.eLo,
      hi: region.eHi,
    });
  };

  const removeRegion = (id: string) =>
    setRegions((prev) => prev.filter((r) => r.id !== id));
  const clearRegions = () => setRegions([]);

  return { regions, addRegion, restoreRegion, removeRegion, clearRegions };
}
