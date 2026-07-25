import { useCallback, useEffect, useRef, useState } from "react";

import { edsElementMap, type EdsElementMapResult } from "../../lib/api";

export const EDS_MAP_DEBOUNCE_MS = 120;
export type EdsMapBackground = "linear" | "none" | "bremsstrahlung";

interface UseEdsElementMapOptions {
  imageId: string | null;
  e0Kev: number;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
}

/** Debounced, abortable EDS map extraction that retains the previous map. */
export function useEdsElementMap({
  imageId,
  e0Kev,
  isOpen,
  onStatus,
}: UseEdsElementMapOptions) {
  const [result, setResult] = useState<EdsElementMapResult | null>(null);
  const [busy, setBusy] = useState(false);
  const timerRef = useRef<number | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const generationRef = useRef(0);

  const cancelPending = useCallback(() => {
    if (timerRef.current != null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    controllerRef.current?.abort();
    controllerRef.current = null;
  }, []);

  useEffect(() => {
    cancelPending();
    setResult(null);
    setBusy(false);
    return cancelPending;
  }, [cancelPending, imageId]);

  const request = useCallback(
    (
      lo: number,
      hi: number,
      background: EdsMapBackground,
      beamEnergy = e0Kev,
    ) => {
      const id = imageId;
      if (!id) return;
      cancelPending();
      const generation = ++generationRef.current;
      const controller = new AbortController();
      controllerRef.current = controller;
      setBusy(true);
      timerRef.current = window.setTimeout(() => {
        timerRef.current = null;
        edsElementMap(id, lo, hi, {
          bg: background,
          e0Kev: background === "bremsstrahlung" ? beamEnergy : undefined,
          signal: controller.signal,
        })
          .then((next) => {
            if (controller.signal.aborted || !isOpen(id)) return;
            setResult(next);
            onStatus(
              id,
              `EDS map: ${lo.toFixed(3)}–${hi.toFixed(3)} keV (${background}), ` +
                `${next.total_counts.toFixed(0)} counts`,
            );
          })
          .catch((error: unknown) => {
            if (controller.signal.aborted) return;
            const message =
              error instanceof Error ? error.message : String(error);
            onStatus(id, `EDS map: ${message}`);
          })
          .finally(() => {
            if (generation === generationRef.current) setBusy(false);
          });
      }, EDS_MAP_DEBOUNCE_MS);
    },
    [cancelPending, e0Kev, imageId, isOpen, onStatus],
  );

  return { mapResult: result, mapBusy: busy, recomputeMap: request };
}
