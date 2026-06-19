import { beforeEach, describe, expect, it } from "vitest";

import { useScribble } from "./scribble";

const reset = () =>
  useScribble.setState({
    active: false,
    imageId: null,
    classId: 1,
    numClasses: 2,
    brush: 6,
    boundary: [],
    strokes: [],
  });

describe("scribble store", () => {
  beforeEach(reset);

  it("begin activates for an image and clears prior strokes", () => {
    const s = useScribble.getState();
    s.startStroke([1, 1]);
    s.begin("img-1");
    const st = useScribble.getState();
    expect(st.active).toBe(true);
    expect(st.imageId).toBe("img-1");
    expect(st.strokes).toHaveLength(0);
    expect(st.classId).toBe(1);
  });

  it("startStroke then addPoint builds a polyline on the active stroke", () => {
    const s = useScribble.getState();
    s.begin("img-1");
    s.setClass(2);
    s.setBrush(4);
    s.startStroke([10, 10]);
    s.addPoint([20, 10]);
    s.addPoint([30, 10]);
    const [stroke] = useScribble.getState().strokes;
    expect(stroke.classId).toBe(2);
    expect(stroke.radius).toBe(4);
    expect(stroke.points).toEqual([
      [10, 10],
      [20, 10],
      [30, 10],
    ]);
  });

  it("addPoint with no active stroke is a no-op", () => {
    useScribble.getState().addPoint([1, 1]);
    expect(useScribble.getState().strokes).toHaveLength(0);
  });

  it("setNumClasses clamps to 2..8 and pulls classId/boundary in range", () => {
    const s = useScribble.getState();
    s.setClass(6);
    s.toggleBoundary(6);
    s.setNumClasses(3);
    const st = useScribble.getState();
    expect(st.numClasses).toBe(3);
    expect(st.classId).toBe(3); // was 6, clamped down
    expect(st.boundary).toEqual([]); // class 6 dropped
    s.setNumClasses(99);
    expect(useScribble.getState().numClasses).toBe(8);
  });

  it("toggleBoundary adds then removes a class", () => {
    const s = useScribble.getState();
    s.toggleBoundary(2);
    expect(useScribble.getState().boundary).toEqual([2]);
    s.toggleBoundary(2);
    expect(useScribble.getState().boundary).toEqual([]);
  });

  it("end deactivates and drops strokes", () => {
    const s = useScribble.getState();
    s.begin("img-1");
    s.startStroke([1, 1]);
    s.end();
    const st = useScribble.getState();
    expect(st.active).toBe(false);
    expect(st.imageId).toBeNull();
    expect(st.strokes).toHaveLength(0);
  });
});
