// jsdom has no canvas, so renderFigure is driven through a recording 2-D
// context. That is enough to pin WHERE things land, which is the part that
// has been wrong: the scale bar used to be drawn only on the overlay tile, so
// exporting from the montage-only view silently produced a figure with no
// bar at all.

import { describe, expect, it, vi } from "vitest";

import { renderFigure, type FigureSource } from "./figure";
import { layoutFigure } from "./figureLayout";

interface FillRect {
  x: number;
  y: number;
  w: number;
  h: number;
  fill: string;
}

function recordingCanvas() {
  const rects: FillRect[] = [];
  const texts: { text: string; x: number; y: number; fill: string }[] = [];
  const ctx = {
    fillStyle: "",
    font: "",
    textAlign: "left",
    globalAlpha: 1,
    imageSmoothingEnabled: true,
    fillRect(x: number, y: number, w: number, h: number) {
      rects.push({ x, y, w, h, fill: String(this.fillStyle) });
    },
    fillText(text: string, x: number, y: number) {
      texts.push({ text, x, y, fill: String(this.fillStyle) });
    },
    measureText: (text: string) => ({ width: text.length * 7 }),
    createImageData: (w: number, h: number) => ({
      data: new Uint8ClampedArray(w * h * 4),
    }),
    putImageData: vi.fn(),
    drawImage: vi.fn(),
  };
  const canvas = {
    width: 0,
    height: 0,
    getContext: () => ctx,
  } as unknown as HTMLCanvasElement;
  return { canvas, rects, texts };
}

const source = (label: string): FigureSource => ({
  label,
  color: "#ff8800",
  rgba: new Uint8ClampedArray(4 * 4 * 4),
  w: 4,
  h: 4,
});

/** The bar is the only 4-px-tall white rect the renderer draws. */
const bars = (rects: FillRect[]) =>
  rects.filter((r) => r.h === 4 && r.fill === "#fff");

const within = (r: FillRect, tile: { x: number; y: number; w: number; h: number }) =>
  r.x >= tile.x && r.x + r.w <= tile.x + tile.w && r.y >= tile.y && r.y <= tile.y + tile.h;

describe("renderFigure scale bar", () => {
  it("draws the bar on the combined overlay tile when there is one", () => {
    const { canvas, rects, texts } = recordingCanvas();
    const tiles = [source("Fe Kα"), source("O Kα")];
    const layout = renderFigure(canvas, tiles, {
      overlay: source("Overlay"),
      columns: 3,
      scaleBar: { fraction: 0.25, label: "200 nm" },
    });
    const placedOverlay = layout.tiles.find((t) => t.overlay)!;
    expect(bars(rects)).toHaveLength(1);
    expect(within(bars(rects)[0], placedOverlay)).toBe(true);
    expect(bars(rects)[0].w).toBe(Math.round(placedOverlay.w * 0.25));
    expect(texts.some((t) => t.text === "200 nm")).toBe(true);
  });

  it("falls back to the first tile when the figure has no overlay", () => {
    const { canvas, rects } = recordingCanvas();
    const layout = renderFigure(canvas, [source("Fe Kα"), source("O Kα")], {
      columns: 3,
      scaleBar: { fraction: 0.25, label: "200 nm" },
    });
    expect(layout.tiles.some((t) => t.overlay)).toBe(false);
    expect(bars(rects)).toHaveLength(1);
    expect(within(bars(rects)[0], layout.tiles[0])).toBe(true);
  });

  it("draws no bar at all when the cube gave none", () => {
    const { canvas, rects } = recordingCanvas();
    renderFigure(canvas, [source("Fe Kα")], { overlay: source("Overlay") });
    expect(bars(rects)).toHaveLength(0);
  });

  it("sizes the canvas to the layout it returns", () => {
    const { canvas } = recordingCanvas();
    const layout = renderFigure(canvas, [source("Fe Kα")], { columns: 2 });
    expect(canvas.width).toBe(layout.width);
    expect(canvas.height).toBe(layout.height);
    expect(layout.width).toBe(layoutFigure(1, { columns: 2 }, false).width);
  });
});
