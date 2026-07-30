// Layout arithmetic for the exported elemental-map figure.
//
// Kept pure and separate from the drawing so it can be tested: jsdom has no
// canvas, so anything that touches a 2D context is untestable in this suite.
// The drawing code reads positions from here and does nothing but paint.
//
// The figure is the standard published layout — a montage of single-element
// maps, each labelled with its element and line, plus the combined overlay
// and a colour legend.

export interface FigureItem {
  /** "Si Kα" */
  label: string;
  /** element colour, used for the label text and the legend chip */
  color: string;
  /** optional second line under the label, e.g. "3.1M net" or "33.2 at%" */
  detail?: string;
}

export interface FigureLayoutOptions {
  /** Rendered size of one map tile in device pixels (tiles are square-ish). */
  tile: number;
  /** Aspect ratio (height / width) of the source maps. */
  aspect: number;
  /** Max tiles per row; the overlay occupies its own trailing slot. */
  columns: number;
  padding: number;
  gap: number;
  labelHeight: number;
  legendHeight: number;
  titleHeight: number;
}

export interface PlacedTile {
  index: number;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Baseline y for the label drawn beneath the tile. */
  labelY: number;
  /** True for the trailing combined-overlay tile. */
  overlay: boolean;
}

export interface FigureLayout {
  width: number;
  height: number;
  tiles: PlacedTile[];
  legendY: number;
  titleY: number;
}

export const FIGURE_DEFAULTS: FigureLayoutOptions = {
  tile: 320,
  aspect: 1,
  columns: 4,
  padding: 24,
  gap: 14,
  labelHeight: 30,
  legendHeight: 34,
  titleHeight: 0,
};

/**
 * Place `count` map tiles (optionally plus a trailing overlay tile) in a grid.
 * Returns the full canvas size so the caller can allocate before drawing.
 */
export function layoutFigure(
  count: number,
  options: Partial<FigureLayoutOptions> = {},
  withOverlay = true,
): FigureLayout {
  const o = { ...FIGURE_DEFAULTS, ...options };
  const total = Math.max(0, count) + (withOverlay ? 1 : 0);
  if (total === 0) {
    return {
      width: o.padding * 2,
      height: o.padding * 2,
      tiles: [],
      legendY: o.padding,
      titleY: o.padding,
    };
  }

  const columns = Math.max(1, Math.min(o.columns, total));
  const rows = Math.ceil(total / columns);
  const tileW = o.tile;
  const tileH = Math.max(1, Math.round(o.tile * o.aspect));
  const cellH = tileH + o.labelHeight;

  const width = o.padding * 2 + columns * tileW + (columns - 1) * o.gap;
  const gridTop = o.padding + o.titleHeight;
  const height =
    gridTop + rows * cellH + (rows - 1) * o.gap + o.legendHeight + o.padding;

  const tiles: PlacedTile[] = [];
  for (let i = 0; i < total; i++) {
    const col = i % columns;
    const row = Math.floor(i / columns);
    const x = o.padding + col * (tileW + o.gap);
    const y = gridTop + row * (cellH + o.gap);
    tiles.push({
      index: i,
      x,
      y,
      w: tileW,
      h: tileH,
      // labels sit in the strip under each tile, vertically centred in it
      labelY: y + tileH + Math.round(o.labelHeight * 0.62),
      overlay: withOverlay && i === total - 1,
    });
  }

  return {
    width,
    height,
    tiles,
    legendY: height - o.padding - Math.round(o.legendHeight * 0.35),
    titleY: o.padding + Math.round(o.titleHeight * 0.7),
  };
}

export interface LegendChip {
  x: number;
  swatch: number;
  text: string;
  color: string;
}

/**
 * Lay legend chips out left to right, measuring each label so they never
 * overlap. `measure` is the canvas text measurer, injected so this stays
 * canvas-free and testable.
 */
export function layoutLegend(
  items: FigureItem[],
  measure: (text: string) => number,
  startX: number,
  swatch = 12,
  gap = 18,
): { chips: LegendChip[]; width: number } {
  let x = startX;
  const chips: LegendChip[] = [];
  for (const item of items) {
    const text = item.detail ? `${item.label}  ${item.detail}` : item.label;
    chips.push({ x, swatch, text, color: item.color });
    x += swatch + 6 + measure(text) + gap;
  }
  return { chips, width: Math.max(0, x - gap - startX) };
}
