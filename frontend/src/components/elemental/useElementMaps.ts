// Fetch a window map per visible species — in ONE request.
//
// This used to fan out N concurrent single-element `/eds/element-map` calls,
// because the batch extraction was reachable only through `/eds/quantify` and
// nobody wanted a Cliff-Lorimer run just to see five maps. `/eds/element-maps`
// (plan #8) removed that constraint: five elements are now one round trip and
// one read of the cube, rather than five of each.
//
// The per-species cache survives the change, and is why the request sends only
// the MISSES: ticking a sixth element fetches that one element, not all six
// again. Keys include the window and the background model, so tuning either
// re-extracts only what actually changed. A superseded set aborts — changing
// the background with five species showing would otherwise leave stale
// responses racing to paint the montage.

import { useCallback, useEffect, useRef, useState } from "react";

import { edsElementMaps } from "../../lib/api";
import type { Species } from "../../lib/spectrum/species";
import type { MapTile } from "../../lib/elemental/mapTile";
import type { EdsMapBackground } from "../../lib/eds/background";

function keyOf(s: Species, bg: EdsMapBackground, e0Kev: number): string {
  const { lo, hi } = s.windows.signal;
  return `${s.symbol}|${lo.toFixed(4)}|${hi.toFixed(4)}|${bg}|${
    bg === "bremsstrahlung" ? e0Kev : 0
  }`;
}

interface Options {
  imageId: string | null;
  /** Only the species that should be mapped — callers pass the visible ones. */
  species: readonly Species[];
  bg: EdsMapBackground;
  e0Kev: number;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
}

export function useEdsElementMaps({
  imageId,
  species,
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

  // A primitive key keeps the effect from re-running on every parent render,
  // where `species` is a fresh array with identical contents.
  const signature = species.map((s) => keyOf(s, bg, e0Kev)).join(",");

  const extract = useCallback(async () => {
    const id = imageId;
    if (!id) return;
    controller.current?.abort();
    const local = new AbortController();
    controller.current = local;

    if (species.length === 0) {
      setTiles([]);
      return;
    }
    const wanted = species.map((s) => ({ species: s, key: keyOf(s, bg, e0Kev) }));
    const misses = wanted.filter((w) => !cache.current.has(w.key));

    setBusy(true);
    try {
      if (misses.length > 0) {
        const result = await edsElementMaps(
          id,
          misses.map((m) => ({
            symbol: m.species.symbol,
            eLo: m.species.windows.signal.lo,
            eHi: m.species.windows.signal.hi,
          })),
          {
            bg,
            e0Kev: bg === "bremsstrahlung" ? e0Kev : undefined,
            signal: local.signal,
          },
        );
        if (local.signal.aborted || !isOpen(id)) return;
        // Entries come back in request order, so they pair with `misses` by
        // index. A species that could not be mapped carries a reason instead
        // of a raster and is reported rather than silently missing from the
        // montage.
        const failed: string[] = [];
        result.maps.forEach((entry, i) => {
          const miss = misses[i];
          if (!miss) return;
          if (!entry.map) {
            failed.push(`${entry.symbol} (${entry.error ?? "no map"})`);
            return;
          }
          cache.current.set(miss.key, {
            symbol: entry.symbol,
            line: entry.line ?? miss.species.transition,
            map: entry.map,
            shape: result.shape,
            totalCounts: entry.total_counts ?? 0,
          });
        });
        if (failed.length > 0) {
          onStatus(id, `EDS maps: skipped ${failed.join(", ")}`);
        }
      }
      if (local.signal.aborted || !isOpen(id)) return;
      setTiles(
        wanted
          .map((w) => cache.current.get(w.key))
          .filter((t): t is MapTile => !!t),
      );
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
