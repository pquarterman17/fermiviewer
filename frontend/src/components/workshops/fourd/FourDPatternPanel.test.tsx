import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import type { Raster16 } from "../../../lib/api";
import { useFourD, type FourDAperture } from "../../../store/fourd";
import FourDPatternPanel from "./FourDPatternPanel";

function raster(w: number, h: number): Raster16 {
  return { data: new Uint16Array(w * h), w, h, vmin: 0, vmax: 1, nFrames: null };
}

const APERTURE: FourDAperture = {
  centerKy: null,
  centerKx: null,
  innerR: 10,
  outerR: 20,
  shape: "disk",
  mode: "bf",
  autoCenter: true,
};

beforeEach(() => {
  useFourD.setState({
    patternRaster: null,
    meanRaster: null,
    aperture: APERTURE,
    probe: null,
    busyPattern: false,
  });
});

describe("FourDPatternPanel aspect ratio", () => {
  it("locks a non-square det_shape's aspect ratio via CSS, not a static height", () => {
    // 144x144 square in the audit report is the failure case AFTER a layout
    // squeeze turned it into a wide rectangle; a genuinely non-square
    // det_shape (e.g. a rectangular direct-electron detector) makes the
    // regression assertion unambiguous: the ratio must be 180:120, and it
    // must survive independent of whatever pixel height the flex layout
    // would otherwise compute.
    useFourD.setState({ patternRaster: raster(180, 120) });
    render(<FourDPatternPanel meta={null} />);
    const canvas = document.querySelector("canvas") as HTMLCanvasElement;
    expect(canvas.style.aspectRatio).toBe("180 / 120");
    expect(canvas.style.height).toBe("");

    const container = canvas.parentElement as HTMLElement;
    expect(container.style.aspectRatio).toBe("180 / 120");
    expect(container.style.height).toBe("");
  });

  it("keeps a square det_shape's 1:1 ratio the same way", () => {
    useFourD.setState({ patternRaster: raster(144, 144) });
    render(<FourDPatternPanel meta={null} />);
    const canvas = document.querySelector("canvas") as HTMLCanvasElement;
    expect(canvas.style.aspectRatio).toBe("144 / 144");
  });

  it("renders nothing pattern-shaped while no pattern is loaded", () => {
    render(<FourDPatternPanel meta={null} />);
    expect(screen.getByText(/Select a dataset/)).toBeVisible();
    expect(document.querySelector("canvas")).toBeNull();
  });
});

describe("FourDPatternPanel auto-center preview", () => {
  it("draws the aperture ring at the mean pattern's intensity centroid, not the geometric center", () => {
    const w = 20;
    const h = 20;
    // What's on screen right now could be a probed pattern — auto-center
    // must still follow the MEAN pattern's beam position, cached separately.
    const displayed = raster(w, h);
    const mean = raster(w, h);
    mean.data[3 * w + 15] = 5000; // single bright pixel at (y=3, x=15)
    useFourD.setState({ patternRaster: displayed, meanRaster: mean });

    render(<FourDPatternPanel meta={null} />);

    const circle = document.querySelector("svg circle") as SVGCircleElement;
    const scale = 260 / w; // VIEW_W / raster.w
    expect(Number(circle.getAttribute("cx"))).toBeCloseTo(15 * scale, 5);
    expect(Number(circle.getAttribute("cy"))).toBeCloseTo(3 * scale, 5);
  });

  it("falls back to the geometric center when no mean pattern is cached yet", () => {
    const w = 20;
    const h = 20;
    useFourD.setState({ patternRaster: raster(w, h), meanRaster: null });

    render(<FourDPatternPanel meta={null} />);

    const circle = document.querySelector("svg circle") as SVGCircleElement;
    const scale = 260 / w;
    expect(Number(circle.getAttribute("cx"))).toBeCloseTo(((w - 1) / 2) * scale, 5);
    expect(Number(circle.getAttribute("cy"))).toBeCloseTo(((h - 1) / 2) * scale, 5);
  });
});
