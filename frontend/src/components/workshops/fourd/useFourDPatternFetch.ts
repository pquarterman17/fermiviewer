// Debounce probe moves on the nav minimap into a /pattern fetch, aborting
// any request a newer probe supersedes. Mirrors the shape of
// workshops/useSpectrumProbe.ts, but stays local to the FourD workshop: v1
// deliberately does NOT hook the main Stage's capture modes (specnav etc.)
// — that integration is flagged as a v2 follow-up in FourDWorkshop's header
// comment — so this hook owns its own small debounce rather than reusing
// useSpectrumProbe's stage-coupled one.

import { useEffect } from "react";

import { fetchFourDPattern } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";

export const FOURD_PATTERN_DEBOUNCE_MS = 75;

export function useFourDPatternFetch(datasetId: string | null): void {
  const probe = useFourD((s) => s.probe);

  useEffect(() => {
    if (!datasetId || !probe) return;
    const controller = new AbortController();
    const { setPatternRaster, setStatus, setBusyPattern } = useFourD.getState();
    setBusyPattern(true);
    const { y, x } = probe;
    const timer = window.setTimeout(() => {
      fetchFourDPattern(datasetId, y, x, { signal: controller.signal })
        .then((raster) => {
          if (!controller.signal.aborted) setPatternRaster(raster);
        })
        .catch((e: unknown) => {
          if (controller.signal.aborted) return;
          setStatus(`pattern: ${(e as Error).message}`);
        })
        .finally(() => {
          if (!controller.signal.aborted) setBusyPattern(false);
        });
    }, FOURD_PATTERN_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [datasetId, probe]);
}
