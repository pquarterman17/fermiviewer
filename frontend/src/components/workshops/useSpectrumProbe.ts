import { useEffect, useRef } from "react";

import { fetchSpectrum, type Spectrum } from "../../lib/api";
import { useViewer } from "../../store/viewer";

export type SpectrumRect = [number, number, number, number];

export const SPECTRUM_PROBE_DEBOUNCE_MS = 80;
// A pure trailing debounce never elapses during a drag: pointermove arrives
// about every 16 ms, so each move resets the timer and the "live" probe shows
// nothing until the pointer stops. Fire at least this often while pixels keep
// arriving, which keeps it live while still capping a drag at ~4 requests/s
// instead of one per frame.
export const SPECTRUM_PROBE_MAX_WAIT_MS = 250;

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
  const lastFiredAt = useRef(0);
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
    // Wait the full debounce when idle, but never postpone past the max wait
    // while the pointer keeps moving.
    const since = Date.now() - lastFiredAt.current;
    const wait =
      since >= SPECTRUM_PROBE_MAX_WAIT_MS
        ? 0
        : Math.min(
            SPECTRUM_PROBE_DEBOUNCE_MS,
            SPECTRUM_PROBE_MAX_WAIT_MS - since,
          );
    const timer = window.setTimeout(() => {
      lastFiredAt.current = Date.now();
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
    }, wait);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [enabled, imageId, pixel]);
}
