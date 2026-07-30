import { describe, expect, it } from "vitest";

import { layoutFigure, layoutLegend } from "./figureLayout";

describe("layoutFigure", () => {
  it("reserves a trailing slot for the overlay tile", () => {
    const layout = layoutFigure(3, { columns: 4 });
    expect(layout.tiles).toHaveLength(4);
    expect(layout.tiles.at(-1)?.overlay).toBe(true);
    expect(layout.tiles.slice(0, 3).every((t) => !t.overlay)).toBe(true);
  });

  it("wraps past the column count", () => {
    const layout = layoutFigure(5, { columns: 3 }); // 5 maps + overlay = 6
    expect(layout.tiles).toHaveLength(6);
    expect(layout.tiles[0].y).toBe(layout.tiles[2].y); // first row
    expect(layout.tiles[3].y).toBeGreaterThan(layout.tiles[0].y); // second row
    expect(layout.tiles[3].x).toBe(layout.tiles[0].x); // aligned columns
  });

  it("never allocates more columns than there are tiles", () => {
    const layout = layoutFigure(1, { columns: 6 }); // 1 map + overlay
    expect(layout.tiles).toHaveLength(2);
    expect(layout.tiles[0].y).toBe(layout.tiles[1].y);
    // canvas is sized for two tiles, not six
    const wide = layoutFigure(5, { columns: 6 });
    expect(wide.width).toBeGreaterThan(layout.width);
  });

  it("sizes tiles to the map aspect ratio", () => {
    const tall = layoutFigure(1, { tile: 100, aspect: 2 }, false);
    expect(tall.tiles[0].w).toBe(100);
    expect(tall.tiles[0].h).toBe(200);
  });

  it("leaves room for labels and the legend", () => {
    const withLegend = layoutFigure(2, { legendHeight: 40 });
    const without = layoutFigure(2, { legendHeight: 0 });
    expect(withLegend.height - without.height).toBe(40);
    expect(withLegend.legendY).toBeLessThan(withLegend.height);
    // labels sit inside the strip beneath their tile
    const tile = withLegend.tiles[0];
    expect(tile.labelY).toBeGreaterThan(tile.y + tile.h);
  });

  it("handles an empty figure without producing a zero-size canvas", () => {
    const layout = layoutFigure(0, {}, false);
    expect(layout.tiles).toEqual([]);
    expect(layout.width).toBeGreaterThan(0);
    expect(layout.height).toBeGreaterThan(0);
  });
});

describe("layoutLegend", () => {
  const measure = (text: string) => text.length * 7;

  it("places chips left to right without overlapping", () => {
    const { chips } = layoutLegend(
      [
        { label: "Si Kα", color: "#eab308" },
        { label: "O Kα", color: "#3b82f6" },
      ],
      measure,
      0,
    );
    expect(chips[0].x).toBe(0);
    expect(chips[1].x).toBeGreaterThan(chips[0].swatch + measure("Si Kα"));
  });

  it("includes the detail text in the chip and its width", () => {
    const plain = layoutLegend([{ label: "Si Kα", color: "#000" }], measure, 0);
    const detailed = layoutLegend(
      [{ label: "Si Kα", color: "#000", detail: "33.2 at%" }],
      measure,
      0,
    );
    expect(detailed.chips[0].text).toContain("33.2 at%");
    expect(detailed.width).toBeGreaterThan(plain.width);
  });
});
