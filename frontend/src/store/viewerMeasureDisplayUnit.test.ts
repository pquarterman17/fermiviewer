// setMeasureDisplayUnit / setAllMeasureDisplayUnits (measure display-units
// feature) — a DISPLAY preference, so these pins focus on what makes it
// one: no undo entry, no geometry touched, per-measure vs. apply-to-all
// scoping, and that the field survives the save/load round trip the same
// way every other unmodelled Measure field already does (viewer.test.ts's
// "keeps every Measure field across a restore" pins the exhaustive case;
// this is the focused one for just this field).

import { beforeEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../lib/api";
import { clientState, sessionSlice } from "./viewerSession";
import { useViewer } from "./viewer";

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

describe("setMeasureDisplayUnit / setAllMeasureDisplayUnits", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState(), true));

  it("per-measure set changes only that measure's override", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const m1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    const m2 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 0.5, y: 0.5 }],
    });
    useViewer.getState().setMeasureDisplayUnit("a", m1, "um");
    const list = useViewer.getState().measures["a"]!;
    expect(list.find((m) => m.id === m1)?.displayUnit).toBe("um");
    expect(list.find((m) => m.id === m2)?.displayUnit).toBeUndefined();
  });

  it("undefined clears the override back to 'image default' (field absent)", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const m1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    useViewer.getState().setMeasureDisplayUnit("a", m1, "nm");
    useViewer.getState().setMeasureDisplayUnit("a", m1, undefined);
    const m = useViewer.getState().measures["a"]!.find((x) => x.id === m1);
    expect(m).toBeDefined();
    // "field absent/undefined" (owner spec) — either representation reads
    // back as "image default"; a JSON round trip (save/load) collapses an
    // undefined-valued key to fully absent either way (JSON.stringify
    // drops it), so this checks the value, not key presence.
    expect(m!.displayUnit).toBeUndefined();
  });

  it("apply-to-all sets every measure on the image; other images untouched", () => {
    const s = useViewer.getState();
    s.ingest([meta("a"), meta("b")]);
    const a1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    const a2 = s.addMeasure("a", {
      kind: "polygon",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }, { x: 1, y: 1 }],
    });
    const b1 = useViewer.getState().addMeasure("b", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    useViewer.getState().setAllMeasureDisplayUnits("a", "mm");
    const listA = useViewer.getState().measures["a"]!;
    const listB = useViewer.getState().measures["b"]!;
    expect(listA.find((m) => m.id === a1)?.displayUnit).toBe("mm");
    expect(listA.find((m) => m.id === a2)?.displayUnit).toBe("mm");
    // the OTHER image's measure never touched
    expect(listB.find((m) => m.id === b1)?.displayUnit).toBeUndefined();
  });

  it("pushes NO undo entry — a display preference, not a measurement edit", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const m1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    const before = useViewer.getState().undoStack.length;
    useViewer.getState().setMeasureDisplayUnit("a", m1, "nm");
    useViewer.getState().setAllMeasureDisplayUnits("a", "um");
    expect(useViewer.getState().undoStack.length).toBe(before);
  });

  it("never touches pts/geometry", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const pts = [{ x: 0, y: 0 }, { x: 1, y: 1 }];
    const m1 = s.addMeasure("a", { kind: "distance", pts });
    useViewer.getState().setMeasureDisplayUnit("a", m1, "um");
    expect(useViewer.getState().measures["a"]!.find((m) => m.id === m1)?.pts).toEqual(pts);
  });
});

describe("Measure.displayUnit — save/load round trip (clientState -> sessionSlice)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState(), true));

  it("survives clientState() -> JSON -> sessionSlice() with its value intact", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const m1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    useViewer.getState().setMeasureDisplayUnit("a", m1, "um");

    const cs = clientState(useViewer.getState());
    // JSON round trip mirrors what both the named-workspace (localStorage)
    // and .fvp (io/project_sections.py `_carry`, verified statically —
    // "displayUnit" is not in `_MEASURE_MODELLED` so it rides through
    // unmodelled, exactly like `color`/`endSymbol`/`text` already do)
    // save paths do to this same object.
    const restored = JSON.parse(JSON.stringify(cs));
    const applied = sessionSlice(
      { images: [meta("a")], client_state: restored },
      useViewer.getState().overlay,
    );
    expect(applied.measures?.["a"]?.find((m) => m.id === m1)?.displayUnit).toBe("um");
  });

  it("an absent override stays absent across the same round trip", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const m1 = s.addMeasure("a", {
      kind: "distance",
      pts: [{ x: 0, y: 0 }, { x: 1, y: 1 }],
    });
    const cs = clientState(useViewer.getState());
    const restored = JSON.parse(JSON.stringify(cs));
    const applied = sessionSlice(
      { images: [meta("a")], client_state: restored },
      useViewer.getState().overlay,
    );
    const m = applied.measures?.["a"]?.find((x) => x.id === m1);
    expect(m).toBeDefined();
    expect("displayUnit" in m!).toBe(false);
  });
});
