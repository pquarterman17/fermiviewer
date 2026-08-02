import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Raster16 } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import FourDNavPanel from "./FourDNavPanel";

afterEach(() => {
  useFourD.getState().reset();
});

function raster(w: number, h: number): Raster16 {
  return { data: new Uint16Array(w * h).fill(50), w, h, vmin: 0, vmax: 100, nFrames: null };
}

describe("FourDNavPanel — degenerate nav-raster shapes", () => {
  it("renders and stays clickable for a 1-row-tall nav image (the .mib (1, 132) default)", () => {
    useFourD.setState({ navRaster: raster(132, 1) });
    render(<FourDNavPanel />);

    const minimap = screen.getByRole("img", {
      name: "Navigation image — click or drag to probe a scan position",
    });
    expect(minimap).toBeVisible();

    // VIEW_W=180 / w=132 => scale ~1.36, so a 1px-tall raster renders as a
    // sub-2px-tall CSS box — jsdom itself never computes real layout
    // (getBoundingClientRect is always all-zero), so mock the box a real
    // browser would actually lay out, the same way FourDWorkshop's own
    // minimap-click test does.
    const scale = 180 / 132;
    vi.spyOn(minimap, "getBoundingClientRect").mockReturnValue({
      x: 0, y: 0, left: 0, top: 0, right: 180, bottom: scale,
      width: 180, height: scale, toJSON: () => ({}),
    });

    fireEvent.pointerDown(minimap, { clientX: 5, clientY: 0 });
    expect(useFourD.getState().probe).toEqual({ y: 0, x: 3 });
  });
});
