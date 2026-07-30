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

  useEffect(() => {
    if (!imageId || !enabled) return;
    const id = imageId;
    let cancelled = false;
    sumCache.current = null;
    setBusy(true);
    fetchSpectrum(id)
      .then((s) => {
        if (cancelled || !isOpen(id)) return;
        sumCache.current = s;
        setSpectrum(s);
        setLabel("Sum spectrum");
        setSource("sum");
        onLoadedRef.current(s);
      })
      .catch((e: Error) => onStatus(id, `EDS spectrum: ${e.message}`))
      .finally(() => {
        if (!cancelled) setBusy(false);
      });
    return () => {
      cancelled = true;
    };
    // isOpen/onStatus are stable callbacks from the explorer; re-running on
    // their identity would refetch the whole cube on every render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId, enabled]);

  useSpectrumProbe({
    imageId,
    pixel: probePixel,
    enabled: enabled && probeActive,
    onSpectrum: (next, rect) => {
      setSpectrum(next);
      setLabel(`px [${rect[0]}, ${rect[1]}]`);
      setSource("live");
    },
    onError: (e) => onStatus(imageId, `EDS spectrum: ${e.message}`),
  });

  /** Show a pixel/ROI spectrum, or the whole-cube sum when `rect` is null. */
  const showRegion = useCallback(
    (rect: Rect1 | null) => {
      const id = imageId;
      if (!id) return;
      setBusy(true);
      fetchSpectrum(id, rect ?? undefined)
        .then((s) => {
          if (!isOpen(id)) return;
          setSpectrum(s);
          setLabel(regionLabel(rect));
          setSource(rect ? "picker" : "sum");
        })
        .catch((e: Error) => onStatus(id, `EDS spectrum: ${e.message}`))
        .finally(() => setBusy(false));
    },
    [imageId, isOpen, onStatus],
  );

  /** Restore the whole-cube sum, from cache when it is already held. */
  const showSum = useCallback(() => {
    const id = imageId;
    if (!id) return;
    if (sumCache.current) {
      setSpectrum(sumCache.current);
      setLabel("Sum spectrum");
      setSource("sum");
      return;
    }
    setBusy(true);
    fetchSpectrum(id)
      .then((s) => {
        if (!isOpen(id)) return;
        sumCache.current = s;
        setSpectrum(s);
        setLabel("Sum spectrum");
        setSource("sum");
      })
      .catch((e: Error) => onStatus(id, `EDS sum: ${e.message}`))
      .finally(() => setBusy(false));
  }, [imageId, isOpen, onStatus]);

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
