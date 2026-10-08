// Colorbar tick labels are absolutely positioned, so the gutter used to be
// sized for the 14 px bar + a 28 px min-width only: at the default 40 px
// tick font the labels ran past the stage edge (right) or onto the
// filmstrip (left). The tick column now reserves the widest label.

import { render } from "@testing-library/react";
import { beforeAll, beforeEach, describe, expect, it } from "vitest";

import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY, useViewer } from "../../store/viewer";
import ColorbarChip from "./ColorbarChip";

beforeAll(() => {
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
});

beforeEach(() => {
  useViewer.setState({
    colorbar: true,
    colorbarSide: "right",
    activeId: "img",
    display: { img: { ...DEFAULT_DISPLAY, lo: 0, hi: 1 } },
  });
  useStageInfo.setState({
    raster: { vmin: 0, vmax: 12345 } as never,
  });
});

const ticksWidth = (font: number) => {
  useViewer.setState({
    display: { img: { ...DEFAULT_DISPLAY, lo: 0, hi: 1, tickFontSize: font } },
  });
  const { container, unmount } = render(<ColorbarChip />);
  const el = container.querySelector(".ticks") as HTMLElement;
  const w = parseFloat(el.style.width);
  const pad = parseFloat((container.querySelector(".body") as HTMLElement).style.paddingTop);
  unmount();
  return { w, pad };
};

describe("ColorbarChip label room", () => {
  it("reserves the widest label's width and half a label of end padding", () => {
    const big = ticksWidth(40);
    // "12000" = 5 glyphs × 0.62 em × 40 px ≈ 124 px (+ tick line/gap)
    expect(big.w).toBeGreaterThanOrEqual(5 * 0.62 * 40);
    expect(big.pad).toBeGreaterThanOrEqual(20);
    const small = ticksWidth(10);
    expect(small.w).toBeLessThan(big.w);
  });
});
