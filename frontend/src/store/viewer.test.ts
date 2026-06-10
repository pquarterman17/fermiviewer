// viewer store — ingest seeding (#34 tilt), measures + undo wiring,
// per-image slices. Pure state tests: no network actions are called.

import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../lib/api";
import { useViewer } from "./viewer";

// snapshot at import time = pristine state incl. actions; setState
// with replace=true restores it between tests
const initialState = useViewer.getState();

function meta(id: string, extra: Partial<ImageMeta> = {}): ImageMeta {
  return {
    id,
    name: `${id}.dm4`,
    kind: "image",
    shape: [96, 128],
    dtype: "float64",
    pixel_size: 0.5,
    pixel_unit: "nm",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
    ...extra,
  } as ImageMeta;
}

beforeEach(() => {
  useViewer.setState(initialState, true);
  localStorage.clear();
});

describe("ingest", () => {
  it("adds images, preserves order, activates the last", () => {
    useViewer.getState().ingest([meta("a"), meta("b")]);
    const s = useViewer.getState();
    expect(s.order).toEqual(["a", "b"]);
    expect(s.activeId).toBe("b");
    expect(s.images["a"].name).toBe("a.dm4");
  });

  it("re-ingesting an id updates meta without duplicating order", () => {
    const { ingest } = useViewer.getState();
    ingest([meta("a")]);
    ingest([meta("a", { name: "renamed.dm4" })]);
    const s = useViewer.getState();
    expect(s.order).toEqual(["a"]);
    expect(s.images["a"].name).toBe("renamed.dm4");
  });

  it("#34: seeds tilt hint from stage_tilt_deg — angle stays 0 (off)", () => {
    useViewer.getState().ingest([
      meta("tilted", { stage_tilt_deg: 52.3 }),
      meta("flat"),
    ]);
    const s = useViewer.getState();
    expect(s.tilts["tilted"]).toEqual({
      angle: 0, // NEVER auto-applied
      seedAngle: 52.3,
      axis: "Y",
      geometry: "cross-section",
    });
    expect(s.tilts["flat"]).toBeUndefined();
  });

  it("#34: re-ingest does not clobber a user-set tilt", () => {
    const { ingest, setTilt } = useViewer.getState();
    ingest([meta("a", { stage_tilt_deg: 52.3 })]);
    setTilt("a", { angle: 52.3, axis: "X", geometry: "surface" });
    ingest([meta("a", { stage_tilt_deg: 52.3 })]);
    expect(useViewer.getState().tilts["a"].angle).toBe(52.3);
    expect(useViewer.getState().tilts["a"].axis).toBe("X");
  });
});

describe("setTilt", () => {
  it("sets and clears the per-image entry", () => {
    const { setTilt } = useViewer.getState();
    setTilt("img", { angle: 30, axis: "Y", geometry: "cross-section" });
    expect(useViewer.getState().tilts["img"].angle).toBe(30);
    setTilt("img", null);
    expect(useViewer.getState().tilts["img"]).toBeUndefined();
  });
});

describe("measures + undo", () => {
  it("addMeasure selects it and pushes one undo entry", () => {
    const { addMeasure } = useViewer.getState();
    const id = addMeasure("img", {
      kind: "distance",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
      ],
    });
    const s = useViewer.getState();
    expect(s.measures["img"]).toHaveLength(1);
    expect(s.selectedMeasure).toBe(id);
    expect(s.undoStack.at(-1)).toMatchObject({ t: "measure-add" });
    expect(s.redoStack).toEqual([]);
  });

  it("undo removes the measure; redo restores it", () => {
    const { addMeasure } = useViewer.getState();
    addMeasure("img", {
      kind: "distance",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
      ],
    });
    useViewer.getState().undo();
    expect(useViewer.getState().measures["img"] ?? []).toHaveLength(0);
    useViewer.getState().redo();
    expect(useViewer.getState().measures["img"]).toHaveLength(1);
  });

  it("updateMeasure replaces pts; removeMeasure drops it and deselects", () => {
    const { addMeasure, updateMeasure, removeMeasure } = useViewer.getState();
    const id = addMeasure("img", {
      kind: "distance",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 0 },
      ],
    });
    updateMeasure("img", id, [
      { x: 0.2, y: 0.2 },
      { x: 0.8, y: 0.8 },
    ]);
    expect(useViewer.getState().measures["img"][0].pts[0].x).toBe(0.2);
    removeMeasure("img", id);
    expect(useViewer.getState().measures["img"]).toHaveLength(0);
    expect(useViewer.getState().selectedMeasure).toBeNull();
  });
});

describe("overlay style", () => {
  it('default endSymbol is "bar" (user request 2026-06-09)', () => {
    expect(useViewer.getState().overlay.endSymbol).toBe("bar");
  });

  it("setOverlay merges and persists to fv_overlay (incl. #42 endSymbol)", () => {
    useViewer.getState().setOverlay({ endSymbol: "circle" });
    expect(useViewer.getState().overlay.endSymbol).toBe("circle");
    const stored = JSON.parse(localStorage.getItem("fv_overlay") ?? "{}") as {
      endSymbol?: string;
    };
    expect(stored.endSymbol).toBe("circle");
  });
});

describe("stack frames (#40)", () => {
  it("tracks the per-image frame index", () => {
    useViewer.getState().setStackFrame("cube", 7);
    expect(useViewer.getState().stackFrames["cube"]).toBe(7);
  });
});
