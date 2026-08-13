import { describe, expect, it } from "vitest";

import { parseSvgSize } from "./chartRaster";
import { chartToSvg, DEFAULT_HEIGHT, DEFAULT_WIDTH } from "./chartSvg";

describe("parseSvgSize", () => {
  it("reads the width/height attributes chartToSvg always sets", () => {
    const svg = chartToSvg({ x: [0, 1], series: [], width: 640, height: 360 });
    expect(parseSvgSize(svg)).toEqual({ width: 640, height: 360 });
  });

  it("falls back to the module defaults when parsing fails", () => {
    expect(parseSvgSize("<svg></svg>")).toEqual({
      width: DEFAULT_WIDTH,
      height: DEFAULT_HEIGHT,
    });
  });
});
