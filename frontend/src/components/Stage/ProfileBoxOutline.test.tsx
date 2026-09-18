import { fireEvent, render } from "@testing-library/react";
import { createRef } from "react";
import { describe, expect, it, vi } from "vitest";

import type { Measure } from "../../store/viewerTypes";
import ProfileBoxOutline from "./ProfileBoxOutline";

const VIEW = { z: 1, px: 0.5, py: 0.5 };
const IMG = { w: 200, h: 200 };
const VP = { w: 200, h: 200 };

const measure = { id: "m1", kind: "profile", pts: [], width: 20 } as unknown as Measure;

/** a horizontal profile line across the middle of the frame */
const PTS = [
  { x: 50, y: 100 },
  { x: 150, y: 100 },
];

function draw(overrides: Partial<Parameters<typeof ProfileBoxOutline>[0]> = {}) {
  const setMeasureWidth = vi.fn();
  const onWidthCommitted = vi.fn();
  const svgRef = createRef<SVGSVGElement>();
  const utils = render(
    <svg ref={svgRef}>
      <ProfileBoxOutline
        measure={measure}
        width={20}
        pts={PTS}
        view={VIEW}
        img={IMG}
        vp={VP}
        imageId="img"
        color="#0f0"
        selected
        common={{}}
        svgRef={svgRef}
        setSelected={vi.fn()}
        setMeasureWidth={setMeasureWidth}
        onWidthCommitted={onWidthCommitted}
        {...overrides}
      />
    </svg>,
  );
  return { ...utils, setMeasureWidth, onWidthCommitted };
}

describe("ProfileBoxOutline", () => {
  it("draws the box at the line's angle, not axis-aligned", () => {
    const { container } = draw({
      pts: [
        { x: 50, y: 50 },
        { x: 150, y: 150 },
      ],
    });
    const poly = container.querySelector("polygon")!;
    const xs = poly
      .getAttribute("points")!
      .split(" ")
      .map((p) => Number(p.split(",")[0]));
    const ys = poly
      .getAttribute("points")!
      .split(" ")
      .map((p) => Number(p.split(",")[1]));
    // a box around a 45° line has four distinct corners; an axis-aligned
    // one would repeat only two x values and two y values
    expect(new Set(xs).size).toBeGreaterThan(2);
    expect(new Set(ys).size).toBeGreaterThan(2);
  });

  it("offers a grip on each long edge only while selected", () => {
    expect(draw().container.querySelectorAll("circle")).toHaveLength(2);
    expect(draw({ selected: false }).container.querySelectorAll("circle"))
      .toHaveLength(0);
  });

  it("turns a perpendicular drag into twice the offset from the centreline", () => {
    const { container, setMeasureWidth } = draw();
    const grip = container.querySelectorAll("g")[0];
    fireEvent.pointerDown(grip.querySelector("line")!);
    // the line runs along y=100; dragging to y=130 is 30 px off-centre, and
    // the box is symmetric, so the width it asks for is 60 — not 30
    fireEvent.pointerMove(grip.querySelector("line")!, { clientX: 100, clientY: 130 });
    expect(setMeasureWidth).toHaveBeenCalledWith("img", "m1", 60);
  });

  it("re-runs the profile on release, because a new width is new numbers", () => {
    const { container, onWidthCommitted } = draw();
    const grip = container.querySelectorAll("g")[0];
    const target = grip.querySelector("line")!;
    fireEvent.pointerDown(target);
    fireEvent.pointerMove(target, { clientX: 100, clientY: 130 });
    expect(onWidthCommitted).not.toHaveBeenCalled();
    fireEvent.pointerUp(target);
    expect(onWidthCommitted).toHaveBeenCalledTimes(1);
  });

  it("ignores a move that did not start on a grip", () => {
    const { container, setMeasureWidth } = draw();
    const grip = container.querySelectorAll("g")[0];
    fireEvent.pointerMove(grip.querySelector("line")!, { clientX: 100, clientY: 130 });
    expect(setMeasureWidth).not.toHaveBeenCalled();
  });
});
