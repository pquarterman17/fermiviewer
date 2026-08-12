// Assemble and download the elemental figure — one path for EDS and EELS.
//
// Both Maps tabs used to carry their own ~40-line copy of this, and the copies
// had already diverged: the EDS figure captioned at% (and only at%), the EELS
// figure captioned nothing, while both on-screen legends showed net counts.
// The figure is the deliverable this whole workspace exists to produce, so it
// is the last place that should differ by modality for no physical reason.
//
// Only the assembly lives here. The tiles are rendered by the same
// renderElementMap/mapDisplayRange pair the montage draws with, and the
// composite comes from the overlay's own canvas, so the exported figure is
// what the user was looking at rather than a second rendering of it.

import { niceScaleLength, formatScaleLength } from "../geometry";
import { mapDisplayRange, renderElementMap } from "../edsMapDisplay";
import { buildElementLut, elementColor } from "./elementColors";
import { renderFigure, type FigureSource } from "./figure";
import { legendDetail, type LegendValue } from "./mapLegend";
import { tileLabel, type MapTile } from "./mapTile";

/** Longest fraction of a tile the bar may span. A bar past this reads as a
 *  measurement of the field of view rather than a reference length. */
const MAX_BAR_FRACTION = 0.4;

export interface ElementalFigureRequest {
  tiles: MapTile[];
  /** The live overlay canvas, or null when the overlay is not on screen.
   *  Without it the figure is the montage alone — no combined tile, no
   *  legend strip, which is exactly what "montage" view shows. */
  overlayCanvas: HTMLCanvasElement | null;
  title: string;
  /** Download filename, e.g. "eds-element-maps.png". */
  filename: string;
  legendValue: LegendValue;
  quantBySymbol?: Record<string, number>;
  /** Scan-pixel size of the cube these maps came from, in `pixelUnit`.
   *  Absent/non-finite ⇒ the cube is uncalibrated and the figure gets no
   *  bar, rather than a bar asserting a length nobody measured. */
  pixelSize?: number | null;
  pixelUnit?: string;
}

/**
 * Bar geometry for a map `widthPx` scan pixels wide, or undefined when the
 * cube carries no usable spatial calibration. `fraction` is of the tile
 * width, which is what `renderFigure` draws against — the tile is the whole
 * map, so tile fraction and map fraction are the same number.
 */
export function figureScaleBar(
  widthPx: number,
  pixelSize: number | null | undefined,
  pixelUnit: string | undefined,
): { fraction: number; label: string } | undefined {
  if (pixelSize == null || !Number.isFinite(pixelSize) || pixelSize <= 0) return undefined;
  if (!pixelUnit || !Number.isFinite(widthPx) || widthPx <= 0) return undefined;
  const across = widthPx * pixelSize;
  const phys = niceScaleLength(across * MAX_BAR_FRACTION);
  if (!Number.isFinite(phys) || phys <= 0 || phys > across) return undefined;
  return { fraction: phys / across, label: formatScaleLength(phys, pixelUnit) };
}

/** Tile → figure panel, tinted and captioned exactly as the montage draws it
 *  on screen (same percentile window, same colour, same label). */
export function tileFigureSource(
  tile: MapTile,
  legendValue: LegendValue,
  quantBySymbol?: Record<string, number>,
): FigureSource {
  const [h, w] = tile.shape;
  const color = elementColor(tile.symbol);
  const range = mapDisplayRange(tile.map, 1, 99);
  return {
    label: tileLabel(tile),
    color,
    detail: legendDetail(tile, legendValue, quantBySymbol),
    rgba: renderElementMap(tile.map, w, h, range, buildElementLut(color)),
    w,
    h,
  };
}

/** Read the composited overlay back off its canvas as a figure panel.
 *  Returns undefined when the overlay is not mounted or the 2-D context is
 *  unavailable — the figure then ships as the montage alone. */
function overlayFigureSource(
  canvas: HTMLCanvasElement | null,
): FigureSource | undefined {
  if (!canvas || canvas.width === 0 || canvas.height === 0) return undefined;
  const data = canvas
    .getContext("2d")
    ?.getImageData(0, 0, canvas.width, canvas.height);
  if (!data) return undefined;
  return {
    label: "Overlay",
    color: "#e6e8ee",
    rgba: data.data,
    w: canvas.width,
    h: canvas.height,
  };
}

/** Columns that keep the panel roughly square, counting the overlay tile. */
export function figureColumns(nTiles: number, hasOverlay: boolean): number {
  const panels = nTiles + (hasOverlay ? 1 : 0);
  return Math.min(4, Math.max(2, Math.ceil(Math.sqrt(panels))));
}

/**
 * Render the figure and hand it to the browser as a PNG download. Resolves
 * once the download has been triggered; rejects nothing — a canvas that
 * cannot produce a blob resolves `false` so the caller reports honestly
 * instead of claiming an export that did not happen.
 */
export async function exportElementalFigure(
  request: ElementalFigureRequest,
): Promise<boolean> {
  const {
    tiles,
    overlayCanvas,
    title,
    filename,
    legendValue,
    quantBySymbol,
    pixelSize,
    pixelUnit,
  } = request;
  if (tiles.length === 0) return false;

  const sources = tiles.map((tile) =>
    tileFigureSource(tile, legendValue, quantBySymbol),
  );
  const overlay = overlayFigureSource(overlayCanvas);
  const canvas = document.createElement("canvas");
  renderFigure(canvas, sources, {
    title,
    overlay,
    columns: figureColumns(tiles.length, !!overlay),
    scaleBar: figureScaleBar(tiles[0].shape[1], pixelSize, pixelUnit),
  });

  if (typeof canvas.toBlob !== "function") return false;
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/png"),
  );
  if (!blob) return false;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
  return true;
}
