// Montage of single-element maps — the grid half of the standard figure.
//
// Each tile is one element's window map, tinted with that element's colour and
// captioned in the same colour, so the reader never has to consult a key to
// know which distribution they are looking at. Clicking a tile focuses that
// element; the tiles are the maps, not thumbnails of something else.

import { useEffect, useRef } from "react";

import { buildElementLut, useElementColors } from "../../lib/elemental/elementColors";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import { mapDisplayRange, renderElementMap } from "../../lib/edsMapDisplay";

export interface MapTile {
  symbol: string;
  line: string;
  /** Full caption override. When absent, the montage/overlay/legend fall
   *  back to "{symbol} {line}α" — the EDS X-ray-line convention. EELS tiles
   *  (edges, not lines) set this explicitly so the caption never grows a
   *  meaningless "α" suffix. */
  caption?: string;
  /** H×W background-subtracted counts. */
  map: number[][];
  shape: [number, number];
  totalCounts: number;
}

/** Stable per-tile identity for React keys and the overlay's per-tile gain
 *  map. `symbol` alone collides when one element carries two species — EELS'
 *  Si-K and Si-L23 (see useEelsMaps.ts) — so every keyed usage goes through
 *  this instead. Safe for EDS too: its species list never repeats a symbol,
 *  so the key is unchanged in effect, just spelled "Fe-K" instead of "Fe". */
export function tileKey(tile: MapTile): string {
  return `${tile.symbol}-${tile.line}`;
}

function Tile({
  tile,
  color,
  lowPct,
  highPct,
  onFocus,
}: {
  tile: MapTile;
  color: string;
  lowPct: number;
  highPct: number;
  onFocus: () => void;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [h, w] = tile.shape;

  useEffect(() => {
    const canvas = ref.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    canvas.width = w;
    canvas.height = h;
    const range = mapDisplayRange(tile.map, lowPct, highPct);
    const image = ctx.createImageData(w, h);
    image.data.set(
      renderElementMap(tile.map, w, h, range, buildElementLut(color)),
    );
    ctx.putImageData(image, 0, 0);
  }, [color, h, highPct, lowPct, tile.map, w]);

  const label = tile.caption ?? `${tile.symbol} ${tile.line}α`;
  return (
    <figure className="fvd-eds-tile">
      <button
        type="button"
        className="fvd-eds-tile-btn"
        onClick={onFocus}
        title={`Focus ${label}`}
      >
        <canvas ref={ref} />
      </button>
      <figcaption style={{ color }}>
        {label}
        <span className="k">{formatCountTick(tile.totalCounts)}</span>
      </figcaption>
    </figure>
  );
}

export default function EdsMapMontage({
  tiles,
  lowPct = 1,
  highPct = 99,
  onFocus,
}: {
  tiles: MapTile[];
  lowPct?: number;
  highPct?: number;
  onFocus: (symbol: string) => void;
}) {
  const colors = useElementColors();
  if (tiles.length === 0) return null;
  return (
    <div className="fvd-eds-montage" role="group" aria-label="Element map montage">
      {tiles.map((tile) => (
        <Tile
          key={tileKey(tile)}
          tile={tile}
          color={colors(tile.symbol)}
          lowPct={lowPct}
          highPct={highPct}
          onFocus={() => onFocus(tile.symbol)}
        />
      ))}
    </div>
  );
}
