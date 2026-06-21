// viewer store — ingest seeding (#34 tilt), measures + undo wiring,
// per-image slices. Pure state tests: no network actions are called.

import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageMeta } from "../lib/api";
import { useViewer } from "./viewer";

// closeImage awaits a network DELETE — stub it so the cleanup logic runs
// without a server. The named-workspace actions also hit the network, so
// stub them too (every other store action exercised here is pure state).
vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../lib/api")>();
  return {
    ...actual,
    closeImage: vi.fn(() => Promise.resolve()),
    saveWorkspaceNamed: vi.fn((name: string) =>
      Promise.resolve({
        slug: name.toLowerCase().replace(/\s+/g, "-"),
        name,
        n_images: 1,
      }),
    ),
    loadWorkspaceNamed: vi.fn((slug: string) =>
      Promise.resolve({
        images: [
          {
            id: "x",
            name: "x.dm4",
            kind: "image",
            shape: [4, 4],
            dtype: "float64",
            pixel_size: 0.5,
            pixel_unit: "nm",
            n_channels: null,
            energy_first: null,
            energy_last: null,
            energy_units: "",
            stage_tilt_deg: null,
            meta: {},
          },
        ],
        client_state: { order: ["x"], activeId: "x" },
        name: slug === "study" ? "Study" : slug,
      }),
    ),
  };
});

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

describe("theming — accent scheme + density", () => {
  it("defaults to the violet scheme at regular density", () => {
    expect(useViewer.getState().accent).toBe("violet");
    expect(useViewer.getState().density).toBe("regular");
  });

  it("setAccent applies data-accent, persists to fv_prefs, updates state", () => {
    useViewer.getState().setAccent("teal");
    expect(useViewer.getState().accent).toBe("teal");
    expect(document.documentElement.getAttribute("data-accent")).toBe("teal");
    const p = JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as {
      accent?: string;
    };
    expect(p.accent).toBe("teal");
  });

  it("setDensity applies data-density, persists, updates state", () => {
    useViewer.getState().setDensity("compact");
    expect(useViewer.getState().density).toBe("compact");
    expect(document.documentElement.getAttribute("data-density")).toBe(
      "compact",
    );
    const p = JSON.parse(localStorage.getItem("fv_prefs") ?? "{}") as {
      density?: string;
    };
    expect(p.density).toBe("compact");
  });
});

describe("named workspaces (WS4b)", () => {
  it("currentWorkspace defaults to null (an unsaved session)", () => {
    expect(useViewer.getState().currentWorkspace).toBeNull();
  });

  it("saveWorkspaceNamed records the named workspace + status", async () => {
    useViewer.getState().ingest([meta("a")]);
    await useViewer.getState().saveWorkspaceNamed("My Study");
    const s = useViewer.getState();
    expect(s.currentWorkspace).toEqual({ slug: "my-study", name: "My Study" });
    expect(s.status).toContain("My Study");
  });

  it("loadWorkspaceNamed replaces the session and tags it", async () => {
    const s0 = useViewer.getState();
    s0.ingest([meta("old1"), meta("old2")]);
    s0.setView("old1", { z: 2, px: 0.5, py: 0.5 }); // pre-load per-image state
    await useViewer.getState().loadWorkspaceNamed("study");
    const s = useViewer.getState();
    expect(s.order).toEqual(["x"]); // old session replaced
    expect(s.activeId).toBe("x");
    expect(s.currentWorkspace).toEqual({ slug: "study", name: "Study" });
    expect(s.undoStack).toEqual([]); // a load is a fresh session
    expect(s.views["old1"]).toBeUndefined(); // stale per-image state cleared
  });
});

describe("edit history (WS4d)", () => {
  it("ingest seeds an Opened origin step at cursor 0", () => {
    useViewer.getState().ingest([meta("a")]);
    const s = useViewer.getState();
    expect(s.history["a"]).toHaveLength(1);
    expect(s.history["a"][0].label).toBe("Opened");
    expect(s.history["a"][0].field).toBe("open");
    expect(s.historyAt["a"]).toBe(0);
  });

  it("a derived image's origin step is labelled Derived", () => {
    useViewer
      .getState()
      .ingestDerived([meta("d", { meta: { derived_from: "a" } })]);
    expect(useViewer.getState().history["d"][0].label).toBe("Derived");
  });

  it("setDisplay logs a labelled step and advances the cursor", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.setDisplay("a", { cmap: "viridis" });
    const h = useViewer.getState().history["a"];
    expect(h).toHaveLength(2);
    expect(h[1].label).toBe("Colormap → viridis");
    expect(h[1].display.cmap).toBe("viridis");
    expect(useViewer.getState().historyAt["a"]).toBe(1);
  });

  it("coalesces consecutive same-control edits into one step", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.setDisplay("a", { gamma: 0.9 });
    s.setDisplay("a", { gamma: 0.8 });
    s.setDisplay("a", { gamma: 0.7 });
    const h = useViewer.getState().history["a"];
    expect(h).toHaveLength(2); // origin + one coalesced gamma step
    expect(h[1].label).toBe("Gamma 0.70");
    expect(h[1].display.gamma).toBe(0.7);
  });

  it("different controls append distinct steps (matches the design example)", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.setDisplay("a", { cmap: "viridis" });
    s.setDisplay("a", { lo: 0.02, hi: 0.98 }); // auto-window pair
    s.setDisplay("a", { gamma: 0.8 });
    expect(useViewer.getState().history["a"].map((x) => x.label)).toEqual([
      "Opened",
      "Colormap → viridis",
      "Auto contrast",
      "Gamma 0.80",
    ]);
  });

  it("a silent setDisplay folds into the current step (no new entry)", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.setDisplay("a", { lo: 0.1, hi: 0.9 }, { silent: true });
    const h = useViewer.getState().history["a"];
    expect(h).toHaveLength(1); // still just Opened
    expect(h[0].display.lo).toBe(0.1); // but its snapshot updated
    expect(useViewer.getState().display["a"].hi).toBe(0.9);
  });

  it("revertHistory scrubs display + cursor; a new edit truncates ahead", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.setDisplay("a", { cmap: "viridis" }); // step 1
    s.setDisplay("a", { gamma: 0.5 }); // step 2
    s.revertHistory("a", 1); // back to the colormap step
    expect(useViewer.getState().historyAt["a"]).toBe(1);
    expect(useViewer.getState().display["a"].gamma).toBe(1); // gamma undone
    expect(useViewer.getState().display["a"].cmap).toBe("viridis");
    // editing from here drops the now-ahead gamma step
    s.setDisplay("a", { invert: true });
    expect(useViewer.getState().history["a"].map((x) => x.label)).toEqual([
      "Opened",
      "Colormap → viridis",
      "Invert on",
    ]);
    expect(useViewer.getState().historyAt["a"]).toBe(2);
  });
});

describe("stack frames (#40)", () => {
  it("tracks the per-image frame index", () => {
    useViewer.getState().setStackFrame("cube", 7);
    expect(useViewer.getState().stackFrames["cube"]).toBe(7);
  });
});

describe("closeImage cleanup", () => {
  it("drops every per-image slice for the closed image (no leaks)", async () => {
    const s = useViewer.getState();
    s.ingest([meta("a"), meta("b")]);
    s.setTilt("a", { angle: 30, axis: "Y", geometry: "cross-section" });
    s.setScaleBar("a", { lengthPhys: 10 });
    s.setStackFrame("a", 3);
    s.setDisplay("a", { gamma: 2 });
    s.setView("a", { z: 2, px: 0.5, py: 0.5 });
    const rid = s.addMeasure("a", {
      kind: "roi",
      pts: [
        { x: 0, y: 0 },
        { x: 1, y: 1 },
      ],
    });
    s.setRoiStats(rid, { mean: 1, std: 1, min: 0, max: 2, area: 4, unit: "nm" });

    await useViewer.getState().closeImage("a");

    const t = useViewer.getState();
    expect(t.images["a"]).toBeUndefined();
    expect(t.measures["a"]).toBeUndefined();
    expect(t.tilts["a"]).toBeUndefined();
    expect(t.scaleBars["a"]).toBeUndefined();
    expect(t.stackFrames["a"]).toBeUndefined();
    expect(t.display["a"]).toBeUndefined();
    expect(t.history["a"]).toBeUndefined();
    expect(t.historyAt["a"]).toBeUndefined();
    expect(t.views["a"]).toBeUndefined();
    expect(t.roiStats[rid]).toBeUndefined();
    expect(t.images["b"]).toBeDefined(); // sibling untouched
    expect(t.history["b"]).toBeDefined(); // sibling history kept
  });
});

// ── audit #9/#10/#12 additions ────────────────────────────────────────

describe("setScaleBar color + unitOverride (audit #10)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("stores color and unitOverride in per-image scalebar slice", () => {
    useViewer.getState().setScaleBar("img1", { color: "#22d3ee", unitOverride: "Å" });
    const sb = useViewer.getState().scaleBars["img1"];
    expect(sb.color).toBe("#22d3ee");
    expect(sb.unitOverride).toBe("Å");
  });

  it("null color and unitOverride clear the overrides", () => {
    useViewer.getState().setScaleBar("img1", { color: "#ff0000", unitOverride: "µm" });
    useViewer.getState().setScaleBar("img1", { color: null, unitOverride: null });
    const sb = useViewer.getState().scaleBars["img1"];
    expect(sb.color).toBeNull();
    expect(sb.unitOverride).toBeNull();
  });
});

describe("setMeasureFontSize (audit #12)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("sets per-annotation font size clamped to [6, 120]", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    const mid = s.addMeasure("a", {
      kind: "box", pts: [{ x: 0.1, y: 0.1 }, { x: 0.9, y: 0.9 }], text: "hi",
    });
    useViewer.getState().setMeasureFontSize("a", mid, 48);
    expect(useViewer.getState().measures["a"]?.find((m) => m.id === mid)?.fontSize).toBe(48);
    // above ceiling clamps to 120
    useViewer.getState().setMeasureFontSize("a", mid, 999);
    expect(useViewer.getState().measures["a"]?.find((m) => m.id === mid)?.fontSize).toBe(120);
    // null clears the override
    useViewer.getState().setMeasureFontSize("a", mid, null);
    expect(useViewer.getState().measures["a"]?.find((m) => m.id === mid)?.fontSize).toBeUndefined();
  });
});

describe("tickCount + tickFontSize in Display (audit #9)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("stores tickCount and tickFontSize in per-image display", () => {
    useViewer.getState().ingest([meta("a")]);
    useViewer.getState().setDisplay("a", { tickCount: 8, tickFontSize: 14 });
    const d = useViewer.getState().display["a"];
    expect(d?.tickCount).toBe(8);
    expect(d?.tickFontSize).toBe(14);
  });
});

// ── audit #11/#13/#15/#16 additions ────────────────────────────────────

describe("deleteLastAnnotation (audit #11)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("removes the last measure when several exist", () => {
    const s = useViewer.getState();
    s.ingest([meta("a")]);
    s.addMeasure("a", { kind: "distance", pts: [{ x: 0, y: 0 }, { x: 1, y: 0 }] });
    const last = s.addMeasure("a", {
      kind: "text", pts: [{ x: 0.5, y: 0.5 }], text: "label",
    });
    expect(useViewer.getState().measures["a"]).toHaveLength(2);
    useViewer.getState().deleteLastAnnotation("a");
    const remaining = useViewer.getState().measures["a"];
    expect(remaining).toHaveLength(1);
    expect(remaining[0].id).not.toBe(last);
  });

  it("is a no-op when there are no measures", () => {
    useViewer.getState().ingest([meta("a")]);
    // must not throw
    useViewer.getState().deleteLastAnnotation("a");
    expect(useViewer.getState().measures["a"] ?? []).toHaveLength(0);
  });
});

describe("resetToOriginal (audit #11)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("walks derived_from chain and activates the root ancestor", () => {
    const s = useViewer.getState();
    // a → b → c (c is derived from b, b from a)
    s.ingest([meta("a")]);
    s.ingestDerived([meta("b", { meta: { derived_from: "a" } })]);
    s.ingestDerived([meta("c", { meta: { derived_from: "b" } })]);
    s.setActive("c");
    expect(useViewer.getState().activeId).toBe("c");
    useViewer.getState().resetToOriginal("c");
    expect(useViewer.getState().activeId).toBe("a");
  });

  it("is a no-op on a non-derived image", () => {
    useViewer.getState().ingest([meta("a")]);
    useViewer.getState().setActive("a");
    useViewer.getState().resetToOriginal("a");
    expect(useViewer.getState().activeId).toBe("a");
  });
});

describe("compare flicker rate + A/B pair (audit #15)", () => {
  beforeEach(() => useViewer.setState(useViewer.getInitialState()));

  it("compareFlickerMs defaults to 600 ms and is clamped >= 100", () => {
    expect(useViewer.getState().compareFlickerMs).toBe(600);
    useViewer.getState().setCompareFlickerMs(250);
    expect(useViewer.getState().compareFlickerMs).toBe(250);
    useViewer.getState().setCompareFlickerMs(50); // below floor
    expect(useViewer.getState().compareFlickerMs).toBe(100);
  });

  it("compareAB defaults to null; can be set and cleared", () => {
    expect(useViewer.getState().compareAB).toBeNull();
    useViewer.getState().setCompareAB([0, 2]);
    expect(useViewer.getState().compareAB).toEqual([0, 2]);
    useViewer.getState().setCompareAB(null);
    expect(useViewer.getState().compareAB).toBeNull();
  });

  it("startCompare resets compareAB to null", () => {
    const s = useViewer.getState();
    s.ingest([meta("a"), meta("b"), meta("c")]);
    s.setCompareAB([0, 2]);
    s.startCompare(["a", "b", "c"]);
    expect(useViewer.getState().compareAB).toBeNull();
  });

  it("exitCompare clears both compareSet and compareAB", () => {
    const s = useViewer.getState();
    s.ingest([meta("a"), meta("b")]);
    s.startCompare(["a", "b"]);
    s.setCompareAB([0, 1]);
    s.exitCompare();
    expect(useViewer.getState().compareSet).toBeNull();
    expect(useViewer.getState().compareAB).toBeNull();
  });
});

describe("side-by-side compare", () => {
  beforeEach(() => {
    useViewer.getState().ingest([meta("a"), meta("b"), meta("c")]);
  });

  it("startSideBySide seeds left=active, right=next-in-order, enters mode", () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide();
    const s = useViewer.getState();
    expect(s.compareMode).toBe("sidebyside");
    expect(s.compareSet).toEqual(["a", "b"]);
    expect(s.sbsLeft).toBe("a");
    expect(s.sbsRight).toBe("b");
    expect(s.sbsActive).toBe("L");
  });

  it("startSideBySide wraps right to the first image when active is last", () => {
    useViewer.getState().setActive("c");
    useViewer.getState().startSideBySide();
    const s = useViewer.getState();
    expect(s.sbsLeft).toBe("c");
    expect(s.sbsRight).toBe("a");
  });

  it("stepSbs scrolls only the targeted pane (wrapping); the other is frozen", () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide(); // L=a, R=b
    useViewer.getState().stepSbs("L", 1); // a → b
    expect(useViewer.getState().sbsLeft).toBe("b");
    expect(useViewer.getState().sbsRight).toBe("b"); // frozen
    expect(useViewer.getState().sbsActive).toBe("L");
    useViewer.getState().stepSbs("L", -1); // b → a
    useViewer.getState().stepSbs("L", -1); // a → c (wrap back)
    expect(useViewer.getState().sbsLeft).toBe("c");
  });

  it("setSbsPane sets a pane directly, focuses it, and syncs compareSet", () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide();
    useViewer.getState().setSbsPane("R", "c");
    const s = useViewer.getState();
    expect(s.sbsRight).toBe("c");
    expect(s.sbsActive).toBe("R");
    expect(s.compareSet).toEqual(["a", "c"]);
  });

  it("setSbsPane ignores unknown image ids", () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide();
    useViewer.getState().setSbsPane("R", "nope");
    expect(useViewer.getState().sbsRight).toBe("b");
  });

  it("setCompareMode('sidebyside') seeds panes from the current compareSet", () => {
    useViewer.getState().startCompare(["b", "c"]);
    useViewer.getState().setCompareMode("sidebyside");
    const s = useViewer.getState();
    expect(s.sbsLeft).toBe("b");
    expect(s.sbsRight).toBe("c");
    expect(s.compareSet).toEqual(["b", "c"]);
  });

  it("setSbsLinked / setSbsActive toggle their flags", () => {
    useViewer.getState().setSbsLinked(false);
    expect(useViewer.getState().sbsLinked).toBe(false);
    useViewer.getState().setSbsActive("R");
    expect(useViewer.getState().sbsActive).toBe("R");
  });

  it("startSideBySide needs >=2 images (no-op with 1)", () => {
    useViewer.setState(initialState, true);
    useViewer.getState().ingest([meta("only")]);
    useViewer.getState().startSideBySide();
    const s = useViewer.getState();
    expect(s.compareSet).toBeNull();
    expect(s.compareMode).not.toBe("sidebyside");
  });

  it("startCompare and exitCompare reset compareMode to split", () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide();
    expect(useViewer.getState().compareMode).toBe("sidebyside");
    // a fresh multi-image compare must not inherit the stale sidebyside mode
    useViewer.getState().startCompare(["a", "b", "c"]);
    expect(useViewer.getState().compareMode).toBe("split");
    useViewer.getState().setCompareMode("sidebyside");
    useViewer.getState().exitCompare();
    expect(useViewer.getState().compareMode).toBe("split");
    expect(useViewer.getState().compareSet).toBeNull();
  });

  it("closeImage drops a side-by-side pane ref that held the closed image", async () => {
    useViewer.getState().setActive("a");
    useViewer.getState().startSideBySide(); // L=a, R=b
    await useViewer.getState().closeImage("a");
    expect(useViewer.getState().sbsLeft).toBeNull();
    expect(useViewer.getState().sbsRight).toBe("b");
  });
});
