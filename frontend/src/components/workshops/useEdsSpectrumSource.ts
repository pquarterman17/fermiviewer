// Which spectrum the EDS explorer is showing, and how it got there.
//
// Extracted from EdsSpectrumImage so the explorer stays under the module-size
// ceiling. It owns the three acquisition paths documented in
// docs/elemental-workspace.md — whole-cube sum, live stage pixel, preview pixel/ROI —
// and the whole-cube cache that makes returning from a pixel instant. Energy
// window, background model and map extraction stay in the explorer: they are
// consumers of whatever spectrum this hook resolves.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchSpectrum, type Spectrum } from "../../lib/api";
import { normalizeEdsSpectrum } from "../../lib/edsSpectrumDisplay";
import type { EdsSpectrumSource } from "../spectrum/SpectrumPanel";
import type { Rect1 } from "./RegionPicker";
import { useSpectrumProbe } from "./useSpectrumProbe";

interface Options {
  imageId: string | null;
  /** False for non-cube images: no spectrum exists to fetch. */
  enabled: boolean;
  /** Stage pixel from the shared probe, or null when it is not armed. */
  probePixel: [number, number] | null;
  probeActive: boolean;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
  /** Fires once per image, after the whole-cube spectrum lands, so the caller
   *  can initialise the energy window against a known energy axis. */
  onLoaded: (spectrum: Spectrum) => void;
}

function regionLabel(rect: Rect1 | null): string {
  if (!rect) return "Sum spectrum";
  return rect[0] === rect[2] && rect[1] === rect[3]
    ? `Pixel [${rect[0]}, ${rect[1]}]`
    : `ROI [${rect[0]}:${rect[2]}, ${rect[1]}:${rect[3]}]`;
}

export function useEdsSpectrumSource({
  imageId,
  enabled,
  probePixel,
  probeActive,
  isOpen,
  onStatus,
  onLoaded,
}: Options) {
  const [spectrum, setSpectrum] = useState<Spectrum | null>(null);
  const [label, setLabel] = useState("Sum spectrum");
  const [source, setSource] = useState<EdsSpectrumSource>("sum");
  const [busy, setBusy] = useState(false);
  const sumCache = useRef<Spectrum | null>(null);
  const onLoadedRef = useRef(onLoaded);
  onLoadedRef.current = onLoaded;

  // One request at a time across the sum / pixel / ROI paths: a new request
  // (or a live-probe sample, or the cached sum) aborts the one in flight, and
  // only the newest may set the spectrum or clear `busy`. Without this, a slow
  // older ROI could land after a newer one — or after a switch to another
  // still-open cube — and replace it.
  const pending = useRef<{ gen: number; abort: AbortController } | null>(null);
  const generation = useRef(0);
  const cancelPending = useCallback(() => {
    generation.current += 1;
    pending.current?.abort.abort();
    pending.current = null;
    setBusy(false);
  }, []);
  const request = useCallback(
    (
      id: string,
      rect: Rect1 | null,
      onSpectrum: (s: Spectrum) => void,
      errorLabel: string,
    ) => {
      pending.current?.abort.abort();
      const gen = ++generation.current;
      const abort = new AbortController();
      pending.current = { gen, abort };
      const current = () => gen === generation.current;
      setBusy(true);
      fetchSpectrum(id, rect ?? undefined, { signal: abort.signal })
        .then((s) => {
          if (current() && isOpen(id)) onSpectrum(s);
        })
        .catch((e: Error) => {
          if (current() && e.name !== "AbortError") onStatus(id, `${errorLabel}: ${e.message}`);
        })
        .finally(() => {
          if (!current()) return;
          pending.current = null;
          setBusy(false);
        });
    },
    [isOpen, onStatus],
  );

  useEffect(() => {
    if (!imageId || !enabled) return;
    const id = imageId;
    sumCache.current = null;
    request(id, null, (s) => {
      sumCache.current = s;
      setSpectrum(s);
      setLabel("Sum spectrum");
      setSource("sum");
      onLoadedRef.current(s);
    }, "EDS spectrum");
    // switching image (or closing the panel) drops whatever is in flight
    return cancelPending;
    // isOpen/onStatus are stable callbacks from the explorer; re-running on
    // their identity would refetch the whole cube on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId, enabled]);

  useSpectrumProbe({
    imageId,
    pixel: probePixel,
    enabled: enabled && probeActive,
    onSpectrum: (next, rect) => {
      cancelPending(); // the live pixel supersedes a pending sum / ROI request
      setSpectrum(next);
      setLabel(`px [${rect[0]}, ${rect[1]}]`);
      setSource("live");
    },
    onError: (e) => onStatus(imageId, `EDS spectrum: ${e.message}`),
  });

  /** Show a pixel/ROI spectrum, or the whole-cube sum when `rect` is null. */
  const showRegion = useCallback(
    (rect: Rect1 | null) => {
      if (!imageId) return;
      request(imageId, rect, (s) => {
        setSpectrum(s);
        setLabel(regionLabel(rect));
        setSource(rect ? "picker" : "sum");
      }, "EDS spectrum");
    },
    [imageId, request],
  );

  /** Restore the whole-cube sum, from cache when it is already held. */
  const showSum = useCallback(() => {
    if (!imageId) return;
    if (sumCache.current) {
      cancelPending(); // an ROI still in flight must not replace the sum
      setSpectrum(sumCache.current);
      setLabel("Sum spectrum");
      setSource("sum");
      return;
    }
    request(imageId, null, (s) => {
      sumCache.current = s;
      setSpectrum(s);
      setLabel("Sum spectrum");
      setSource("sum");
    }, "EDS sum");
  }, [imageId, request, cancelPending]);

  // EDS controls and line libraries work in keV; normalise here so every
  // consumer (plot, integration, CSV) sees one unit.
  const displaySpectrum = useMemo(
    () => (spectrum ? normalizeEdsSpectrum(spectrum) : null),
    [spectrum],
  );

  return {
    spectrum,
    displaySpectrum,
    label,
    source,
    busy,
    showSum,
    showRegion,
  };
}
