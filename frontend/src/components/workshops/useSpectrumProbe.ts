import { useEffect, useRef } from "react";

import { fetchSpectrum, type Spectrum } from "../../lib/api";
import { useViewer } from "../../store/viewer";

export type SpectrumRect = [number, number, number, number];

export const SPECTRUM_PROBE_DEBOUNCE_MS = 80;

interface SpectrumProbeOptions {
  imageId: string | null;
  pixel: [number, number] | null;
  enabled: boolean;
  onSpectrum: (spectrum: Spectrum, rect: SpectrumRect) => void;
  onError: (error: Error) => void;
}

/** Debounce stage pixels and abort any spectrum request they supersede. */
export function useSpectrumProbe({
  imageId,
  pixel,
  enabled,
  onSpectrum,
  onError,
}: SpectrumProbeOptions): void {
  const onSpectrumRef = useRef(onSpectrum);
  const onErrorRef = useRef(onError);
  onSpectrumRef.current = onSpectrum;
  onErrorRef.current = onError;

  useEffect(
    () => () => {
      const viewer = useViewer.getState();
      if (viewer.captureMode === "specnav") viewer.setCaptureMode("none");
    },
    [],
  );

  useEffect(() => {
    if (!enabled || !imageId || !pixel) return;
    const controller = new AbortController();
    const [row, col] = pixel;
    const rect: SpectrumRect = [row, col, row, col];
    const timer = window.setTimeout(() => {
      fetchSpectrum(imageId, rect, { signal: controller.signal })
        .then((spectrum) => {
          if (!controller.signal.aborted) {
            onSpectrumRef.current(spectrum, rect);
          }
        })
        .catch((error: unknown) => {
          if (controller.signal.aborted) return;
          onErrorRef.current(
            error instanceof Error ? error : new Error(String(error)),
          );
        });
    }, SPECTRUM_PROBE_DEBOUNCE_MS);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, imageId, pixel]);
}
