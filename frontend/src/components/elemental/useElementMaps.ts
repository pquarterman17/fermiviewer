// Fetch one window map per selected element.
//
// Requests run concurrently and are keyed by element+window+background, so
// ticking a sixth element fetches only that element rather than re-extracting
// the five already on screen. A superseded set aborts: changing the background
// model with five elements selected would otherwise leave five in-flight
// requests racing to paint the montage.

import { useCallback, useEffect, useRef, useState } from "react";

import { edsElementMap } from "../../lib/api";
import type { IdentifiedElement } from "../../lib/elemental/identify";
import type { MapTile } from "./MapMontage";
import type { EdsMapBackground } from "../workshops/useEdsElementMap";

function keyOf(
  element: IdentifiedElement,
  bg: EdsMapBackground,
  e0Kev: number,
): string {
  return `${element.symbol}|${element.eLo.toFixed(4)}|${element.eHi.toFixed(
    4,
  )}|${bg}|${bg === "bremsstrahlung" ? e0Kev : 0}`;
}

interface Options {
  imageId: string | null;
  elements: IdentifiedElement[];
  bg: EdsMapBackground;
  e0Kev: number;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
}

export function useEdsElementMaps({
  imageId,
  elements,
  bg,
  e0Kev,
  isOpen,
  onStatus,
}: Options) {
  const [tiles, setTiles] = useState<MapTile[]>([]);
  const [busy, setBusy] = useState(false);
  const cache = useRef(new Map<string, MapTile>());
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    cache.current.clear();
    setTiles([]);
  }, [imageId]);

  const selected = elements.filter((e) => e.selected);
  // A primitive key keeps the effect from re-running on every parent render,
  // where `elements` is a fresh array with identical contents.
  const signature = selected
    .map((e) => keyOf(e, bg, e0Kev))
    .join(",");

  const extract = useCallback(async () => {
    const id = imageId;
    if (!id) return;
    controller.current?.abort();
    const local = new AbortController();
    controller.current = local;

    const wanted = elements.filter((e) => e.selected);
    if (wanted.length === 0) {
      setTiles([]);
      return;
    }
    setBusy(true);
    try {
      const results = await Promise.all(
        wanted.map(async (element) => {
          const key = keyOf(element, bg, e0Kev);
          const hit = cache.current.get(key);
          if (hit) return hit;
          const result = await edsElementMap(id, element.eLo, element.eHi, {
            bg,
            e0Kev: bg === "bremsstrahlung" ? e0Kev : undefined,
            signal: local.signal,
          });
          const tile: MapTile = {
            symbol: element.symbol,
            line: element.line,
            map: result.map,
            shape: result.shape,
            totalCounts: result.total_counts,
          };
          cache.current.set(key, tile);
          return tile;
        }),
      );
      if (local.signal.aborted || !isOpen(id)) return;
      setTiles(results);
    } catch (error: unknown) {
      if (local.signal.aborted) return;
      const message = error instanceof Error ? error.message : String(error);
      onStatus(id, `EDS maps: ${message}`);
    } finally {
      if (controller.current === local) setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bg, e0Kev, imageId, isOpen, onStatus, signature]);

  useEffect(() => {
    void extract();
    return () => controller.current?.abort();
  }, [extract]);

  return { tiles, mapsBusy: busy, refreshMaps: extract };
}
