// Fetch a window map per visible EELS species — in ONE request. Mirrors
// useElementMaps.ts's cache-misses-only pattern (see that file's header for
// why the request sends only the misses and why a superseded set aborts).
//
// EDS threads a shared background MODE (`bg`/`e0Kev`) through every request
// because its background is a property of the whole cube's fit. EELS has no
// such thing: each species carries its OWN signal window and its OWN
// optional background window (item 16 auto-places it, but it stays
// per-species and user-adjustable), so those ride on the Species itself.
// `method` (powerlaw/exponential) is the one knob that genuinely applies
// uniformly to every request, mirroring /eels/maps' own per-request default.

import { useCallback, useEffect, useRef, useState } from "react";

import { eelsMaps } from "../../lib/api";
import type { Species } from "../../lib/spectrum/species";
import type { MapTile } from "../../lib/elemental/mapTile";

function keyOf(s: Species, method: string): string {
  const { lo, hi } = s.windows.signal;
  const bg = s.windows.background;
  const bgKey = bg ? `${bg.lo.toFixed(4)}|${bg.hi.toFixed(4)}` : "none";
  return `${s.symbol}-${s.transition}|${lo.toFixed(4)}|${hi.toFixed(4)}|${bgKey}|${method}`;
}

interface Options {
  imageId: string | null;
  /** Only the species that should be mapped — callers pass the visible ones. */
  species: readonly Species[];
  method: string;
  isOpen: (id: string | null) => id is string;
  onStatus: (id: string | null, message: string) => void;
}

export function useEelsElementMaps({
  imageId,
  species,
  method,
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
  const signature = species.map((s) => keyOf(s, method)).join(",");

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
    const wanted = species.map((s) => ({ species: s, key: keyOf(s, method) }));
    const misses = wanted.filter((w) => !cache.current.has(w.key));

    setBusy(true);
    try {
      if (misses.length > 0) {
        const result = await eelsMaps(
          id,
          misses.map((m) => ({
            label: `${m.species.symbol}-${m.species.transition}`,
            signal: { lo: m.species.windows.signal.lo, hi: m.species.windows.signal.hi },
            background: m.species.windows.background
              ? {
                  lo: m.species.windows.background.lo,
                  hi: m.species.windows.background.hi,
                }
              : undefined,
            method,
          })),
          { signal: local.signal },
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
            failed.push(`${miss.species.symbol}-${miss.species.transition} (${entry.error ?? "no map"})`);
            return;
          }
          cache.current.set(miss.key, {
            symbol: miss.species.symbol,
            line: miss.species.transition,
            caption: `${miss.species.symbol} ${miss.species.transition}`,
            map: entry.map,
            shape: result.shape,
            totalCounts: entry.total_counts ?? 0,
          });
        });
        if (failed.length > 0) {
          onStatus(id, `EELS maps: skipped ${failed.join(", ")}`);
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
      onStatus(id, `EELS maps: ${message}`);
    } finally {
      if (controller.current === local) setBusy(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [imageId, isOpen, method, onStatus, signature]);

  useEffect(() => {
    void extract();
    return () => controller.current?.abort();
  }, [extract]);

  return { tiles, mapsBusy: busy, refreshMaps: extract };
}
