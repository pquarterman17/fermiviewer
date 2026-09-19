import { fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useViewer } from "../../store/viewer";
import LayersOverlay from "./LayersOverlay";

// px/py are the view centre as a FRACTION of the image; 0.5 centres it, so
// with a 200 px image in a 200 px viewport image coords map 1:1 to screen
const VIEW = { z: 1, px: 0.5, py: 0.5 };
const IMG = { w: 200, h: 200 };
const VP = { w: 200, h: 200 };

const overlayState = (tiltDeg?: number) => ({
  imageId: "img",
  axis: "y" as const,
  interfaces: [50, 120],
  traces: [null, null],
  lateralRange: [0, 200] as [number, number],
  ...(tiltDeg === undefined ? {} : { tiltDeg }),
});

const draw = () =>
  render(<LayersOverlay imageId="img" view={VIEW} img={IMG} vp={VP} />);

/** the dashed interface lines, in draw order */
const lines = (c: HTMLElement) =>
  Array.from(c.querySelectorAll("line")).filter(
    (l) => l.getAttribute("stroke") === "#f59e0b",
  );

afterEach(() => {
  useViewer.setState({
    layersOverlay: null, layersEdit: false, layersTiltReq: null,
  });
});

describe("LayersOverlay tilt", () => {
  it("draws level lines when no tilt has been applied", () => {
    useViewer.setState({ layersOverlay: overlayState() });
    const { container } = draw();
    for (const line of lines(container)) {
      expect(line.getAttribute("y1")).toBe(line.getAttribute("y2"));
    }
  });

  it("tilts every interface by the same angle, about the lateral midpoint", () => {
    useViewer.setState({ layersOverlay: overlayState(10) });
    const { container } = draw();
    const drawn = lines(container);
    expect(drawn).toHaveLength(2);

    const rise = (l: Element) =>
      Number(l.getAttribute("y2")) - Number(l.getAttribute("y1"));
    // ONE angle for the stack: parallel layers cannot converge, and a
    // per-interface angle would let two of them cross
    expect(rise(drawn[0])).toBeCloseTo(rise(drawn[1]), 6);
    // A positive tilt makes the interface RISE to the right, matching
    // `calc/tilted_profile`'s sampler, where a constant-depth line is
    // `row = centre - lateral·sin θ`. The sign is load-bearing: the handle
    // publishes this angle straight to `/analyze/layers`, and the negation
    // of it turns one interface into seven.
    expect(rise(drawn[0])).toBeCloseTo(-200 * Math.tan(Math.PI / 18), 3);

    // pivoting about the midpoint keeps each line's own depth at the centre,
    // so raising the tilt does not sweep the stack off the region
    const midY = (l: Element) =>
      (Number(l.getAttribute("y1")) + Number(l.getAttribute("y2"))) / 2;
    expect(midY(drawn[0])).toBeCloseTo(50, 6);
    expect(midY(drawn[1])).toBeCloseTo(120, 6);
  });

  it("shows the rotate handle only while editing", () => {
    useViewer.setState({ layersOverlay: overlayState(0), layersEdit: false });
    const { container, rerender } = draw();
    expect(container.querySelectorAll("circle")).toHaveLength(0);

    useViewer.setState({ layersEdit: true });
    rerender(<LayersOverlay imageId="img" view={VIEW} img={IMG} vp={VP} />);
    // a visible dot plus the larger invisible hit target beneath it
    expect(container.querySelectorAll("circle")).toHaveLength(2);
  });

  it("publishes the sign the backend integrates along", () => {
    // Drag the handle DOWNWARD: the line must follow the pointer, and the
    // angle sent out must be NEGATIVE, because a stack whose interface
    // falls to the right is a negative tilt in the sampler's convention.
    useViewer.setState({ layersOverlay: overlayState(0), layersEdit: true });
    const { container } = draw();
    const hit = container.querySelectorAll("circle")[1];
    fireEvent.pointerDown(hit);
    fireEvent.pointerMove(hit, { clientX: 200, clientY: 130 });
    fireEvent.pointerUp(hit);
    const published = useViewer.getState().layersTiltReq;
    expect(published).not.toBeNull();
    expect(published!).toBeLessThan(0);
  });

  it("draws nothing for another image's overlay", () => {
    useViewer.setState({ layersOverlay: overlayState(0) });
    const { container } = render(
      <LayersOverlay imageId="other" view={VIEW} img={IMG} vp={VP} />,
    );
    expect(container.querySelector("svg")).toBeNull();
  });
});
