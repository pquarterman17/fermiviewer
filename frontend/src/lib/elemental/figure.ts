// Draw the assembled elemental-map figure: montage tiles labelled in each
// element's colour, the combined overlay, and a colour legend.
//
// All arithmetic lives in figureLayout.ts; this module only paints, so the
// part that can be got wrong is the part that is under test.

import {
  layoutFigure,
  layoutLegend,
  type FigureItem,
  type FigureLayoutOptions,
} from "./figureLayout";

export interface FigureSource extends FigureItem {
  /** RGBA raster of the rendered map, already colourised. */
  rgba: Uint8ClampedArray;
  w: number;
  h: number;
}

export interface FigureRenderOptions extends Partial<FigureLayoutOptions> {
  title?: string;
  /** Page background; the tiles themselves stay black. */
  background?: string;
  /** Colour for labels and the title. */
  textColor?: string;
  /** Draw the trailing combined tile and the legend. */
  overlay?: FigureSource;
  /** Physical bar drawn on the overlay tile, e.g. "200 nm". */
  scaleBar?: { fraction: number; label: string };
}

function putRaster(
  ctx: CanvasRenderingContext2D,
  source: { rgba: Uint8ClampedArray; w: number; h: number },
  x: number,
  y: number,
  w: number,
  h: number,
): void {
  // An offscreen canvas at the raster's native size lets drawImage do the
  // scaling; putImageData ignores transforms and would paste 1:1.
  const buffer = document.createElement("canvas");
  buffer.width = source.w;
  buffer.height = source.h;
  const bctx = buffer.getContext("2d");
  if (!bctx) return;
  const image = bctx.createImageData(source.w, source.h);
  image.data.set(source.rgba);
  bctx.putImageData(image, 0, 0);
  // Element maps are low-resolution next to the figure; smoothing them turns
  // pixel-level structure into mush, so scale them hard-edged.
  ctx.imageSmoothingEnabled = false;
  ctx.drawImage(buffer, 0, 0, source.w, source.h, x, y, w, h);
  ctx.imageSmoothingEnabled = true;
}

/**
 * Render the figure into `canvas`, resizing it to fit. Returns the layout so
 * callers can report the produced dimensions.
 */
export function renderFigure(
  canvas: HTMLCanvasElement,
  tiles: FigureSource[],
  options: FigureRenderOptions = {},
) {
  const {
    title,
    background = "#0b0d12",
    textColor = "#e6e8ee",
    overlay,
    scaleBar,
    ...layoutOptions
  } = options;

  const first = tiles[0] ?? overlay;
  const aspect = first ? first.h / first.w : 1;
  const titleHeight = title ? (layoutOptions.titleHeight ?? 34) : 0;
  const legend = overlay ? [...tiles] : [];
  const layout = layoutFigure(
    tiles.length,
    { ...layoutOptions, aspect, titleHeight, legendHeight: legend.length ? 34 : 0 },
    !!overlay,
  );

  canvas.width = layout.width;
  canvas.height = layout.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return layout;

  ctx.fillStyle = background;
  ctx.fillRect(0, 0, layout.width, layout.height);

  if (title) {
    ctx.fillStyle = textColor;
    ctx.font = "600 20px system-ui, sans-serif";
    ctx.textAlign = "left";
    ctx.fillText(title, layoutOptions.padding ?? 24, layout.titleY);
  }

  for (const placed of layout.tiles) {
    const source = placed.overlay ? overlay : tiles[placed.index];
    if (!source) continue;
    ctx.fillStyle = "#000";
    ctx.fillRect(placed.x, placed.y, placed.w, placed.h);
    putRaster(ctx, source, placed.x, placed.y, placed.w, placed.h);

    ctx.textAlign = "center";
    ctx.font = "600 15px system-ui, sans-serif";
    // The label carries the colour, which is the whole point of the figure:
    // the reader maps tile → element without consulting a separate key.
    ctx.fillStyle = placed.overlay ? textColor : source.color;
    const centre = placed.x + placed.w / 2;
    ctx.fillText(source.label, centre, placed.labelY);
    if (source.detail) {
      ctx.font = "12px system-ui, sans-serif";
      ctx.fillStyle = textColor;
      ctx.globalAlpha = 0.7;
      ctx.fillText(source.detail, centre, placed.labelY + 15);
      ctx.globalAlpha = 1;
    }

    if (placed.overlay && scaleBar) {
      const barW = Math.round(placed.w * scaleBar.fraction);
      const barX = placed.x + placed.w - barW - 12;
      const barY = placed.y + placed.h - 18;
      ctx.fillStyle = "#fff";
      ctx.fillRect(barX, barY, barW, 4);
      ctx.font = "600 12px system-ui, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(scaleBar.label, barX + barW / 2, barY - 5);
    }
  }

  if (legend.length > 0) {
    ctx.font = "13px system-ui, sans-serif";
    ctx.textAlign = "left";
    const { chips, width } = layoutLegend(
      legend,
      (text) => ctx.measureText(text).width,
      0,
    );
    const offset = Math.max(
      layoutOptions.padding ?? 24,
      (layout.width - width) / 2,
    );
    for (const chip of chips) {
      ctx.fillStyle = chip.color;
      ctx.fillRect(offset + chip.x, layout.legendY - chip.swatch + 2, chip.swatch, chip.swatch);
      ctx.fillStyle = textColor;
      ctx.fillText(chip.text, offset + chip.x + chip.swatch + 6, layout.legendY);
    }
  }

  return layout;
}
