import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BatchRunResult } from "./api/batch";
import {
  importBatchRecipePreset,
  loadBatchRecipePresets,
  saveBatchRecipePreset,
  storeBatchRecipePresets,
} from "./batchRecipePresets";

const runBatchRecipe = vi.fn();
vi.mock("./api/batch", () => ({
  runBatchRecipe: (...args: unknown[]) => runBatchRecipe(...args),
}));

import {
  isRecording,
  loadMacro,
  macroLegacyCount,
  macroOpSteps,
  record,
  recordPathOp,
  replayMacro,
  setMacroFromRecipe,
  startRecording,
  stopRecording,
} from "./macro";

function fetchOk(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

describe("macro record/replay", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
  });

  afterEach(() => {
    if (isRecording()) stopRecording();
  });

  it("classifies a mappable filter call as an op step and an unmappable one as legacy", () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 2 } });
    record("/api/filter", { image_id: "a", kind: "crop", params: { row0: 1, col0: 1, row1: 5, col1: 5 } });
    const { total, legacy } = stopRecording();
    expect(total).toBe(2);
    expect(legacy).toBe(1);

    const macro = loadMacro();
    expect(macro[0]).toEqual({ kind: "op", op: "gaussian", params: { sigma: 2 } });
    expect(macro[1].kind).toBe("legacy");
  });

  it("ignores POSTs outside the recordable path set", () => {
    startRecording();
    record("/api/session/open", { paths: ["a"] });
    expect(stopRecording().total).toBe(0);
  });

  it("recordPathOp always captures a legacy step", () => {
    startRecording();
    recordPathOp("/api/image/{id}/fft");
    const { total, legacy } = stopRecording();
    expect(total).toBe(1);
    expect(legacy).toBe(1);
  });

  it("macroOpSteps drops legacy steps and keeps recipe order", () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 2 } });
    record("/api/eds/quantify", {
      image_id: "a", elements: ["Fe", "O"], method: "cliff-lorimer",
      thickness_nm: 100, take_off_angle_deg: 20,
    });
    recordPathOp("/api/image/{id}/fft");
    record("/api/filter", { image_id: "a", kind: "flipv", params: {} });
    stopRecording();

    expect(macroOpSteps()).toEqual([
      { op: "gaussian", params: { sigma: 2 } },
      {
        op: "eds_quantify",
        params: {
          elements: "Fe,O", method: "cliff-lorimer",
          thickness_nm: 100, take_off_angle_deg: 20,
        },
      },
      { op: "flipv", params: {} },
    ]);
    expect(macroLegacyCount()).toBe(1);
  });

  it("round-trips record -> serialize -> replay to the same op list", async () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 1.5 } });
    record("/api/filter", { image_id: "a", kind: "median", params: { window_size: 3 } });
    stopRecording();

    const persisted = JSON.parse(localStorage.getItem("fv_macro")!) as unknown[];
    expect(persisted).toEqual([
      { kind: "op", op: "gaussian", params: { sigma: 1.5 } },
      { kind: "op", op: "median", params: { window_size: 3 } },
    ]);

    const derivedA = { id: "b", shape: [4, 4] };
    const derivedB = { id: "c", shape: [4, 4] };
    const result = (outputs: unknown): BatchRunResult => ({
      version: 1, steps: [], succeeded: 1, failed: 0,
      outputs: [outputs],
    } as unknown as BatchRunResult);
    runBatchRecipe
      .mockResolvedValueOnce(result({ image_id: "a", status: "done", derived: derivedA, values: [] }))
      .mockResolvedValueOnce(result({ image_id: "b", status: "done", derived: derivedB, values: [] }));

    const seen: unknown[] = [];
    const n = await replayMacro("a", (m) => seen.push(m));

    expect(n).toBe(2);
    expect(seen).toEqual([derivedA, derivedB]);
    expect(runBatchRecipe.mock.calls[0][0]).toEqual(["a"]);
    expect(runBatchRecipe.mock.calls[0][1]).toEqual([{ op: "gaussian", params: { sigma: 1.5 } }]);
    expect(runBatchRecipe.mock.calls[1][0]).toEqual(["b"]);
    expect(runBatchRecipe.mock.calls[1][1]).toEqual([{ op: "median", params: { window_size: 3 } }]);
  });

  it("replay throws on a failed op step and reports which step", async () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 1 } });
    stopRecording();
    runBatchRecipe.mockResolvedValue({
      version: 1, steps: [], succeeded: 0, failed: 1,
      outputs: [{ image_id: "a", name: "a.dm4", status: "error", error: "boom", derived: null, values: [] }],
    } satisfies BatchRunResult);

    await expect(replayMacro("a", () => {})).rejects.toThrow("gaussian");
    await expect(replayMacro("a", () => {})).rejects.toThrow("boom");
  });

  it("replay with zero recorded steps is a no-op that resolves immediately", async () => {
    expect(loadMacro()).toEqual([]);
    const seen: unknown[] = [];
    await expect(replayMacro("a", (m) => seen.push(m))).resolves.toBe(0);
    expect(seen).toEqual([]);
  });

  it("replay stops (fail-fast) when a legacy step's endpoint 404s — same policy as an op-step failure", async () => {
    localStorage.setItem(
      "fv_macro",
      JSON.stringify([
        { kind: "legacy", path: "/api/image/{id}/fft", body: {} },
        { kind: "legacy", path: "/api/image/{id}/never-reached", body: {} },
      ]),
    );
    const fetchMock = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      json: async () => ({ detail: "Not Found" }),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await expect(replayMacro("a", () => {})).rejects.toThrow(
      "step 1 (/api/image/{id}/fft): Not Found",
    );
    // the second (renamed/removed-endpoint) step is never attempted —
    // replay does not "mark failed and continue"
    expect(fetchMock).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("replays a legacy step through its original wire call", async () => {
    localStorage.setItem(
      "fv_macro",
      JSON.stringify([{ kind: "legacy", path: "/api/image/{id}/fft", body: {} }]),
    );
    const fetchMock = vi.fn().mockResolvedValue(
      fetchOk({ id: "fft-1", shape: [4, 4] }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const seen: unknown[] = [];
    const n = await replayMacro("a", (m) => seen.push(m));
    expect(n).toBe(1);
    expect(seen).toEqual([{ id: "fft-1", shape: [4, 4] }]);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/image/a/fft",
      expect.objectContaining({ method: "POST" }),
    );
    vi.unstubAllGlobals();
  });

  it("migrates a pre-convergence {path, body} macro without crashing", () => {
    localStorage.setItem(
      "fv_macro",
      JSON.stringify([
        { path: "/api/filter", body: { kind: "gaussian", params: { sigma: 2 } } },
        { path: "/api/analyze/vdf", body: { center: [1, 1], radius: 5 } },
      ]),
    );
    const macro = loadMacro();
    expect(macro).toEqual([
      { kind: "op", op: "gaussian", params: { sigma: 2 } },
      { kind: "legacy", path: "/api/analyze/vdf", body: { center: [1, 1], radius: 5 } },
    ]);
    expect(macroOpSteps(macro)).toEqual([{ op: "gaussian", params: { sigma: 2 } }]);
  });

  it("tolerates garbage in localStorage", () => {
    localStorage.setItem("fv_macro", "not json");
    expect(loadMacro()).toEqual([]);
    localStorage.setItem("fv_macro", JSON.stringify([null, 42, { foo: "bar" }]));
    expect(loadMacro()).toEqual([]);
  });

  it("tolerates a non-array top-level JSON value (e.g. a stray {})", () => {
    localStorage.setItem("fv_macro", JSON.stringify({ not: "an array" }));
    expect(loadMacro()).toEqual([]);
  });

  it("stopRecording surfaces a localStorage quota error instead of throwing", () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 2 } });
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });

    try {
      let result: { total: number; legacy: number; persisted: boolean } | undefined;
      expect(() => { result = stopRecording(); }).not.toThrow();

      expect(result).toEqual({ total: 1, legacy: 0, persisted: false });
      expect(isRecording()).toBe(false); // still stops recording even if the save failed
    } finally {
      setItem.mockRestore();
    }
  });

  it("setMacroFromRecipe surfaces a localStorage quota error instead of throwing", () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota exceeded", "QuotaExceededError");
    });

    try {
      let result: { n: number; persisted: boolean } | undefined;
      expect(() => {
        result = setMacroFromRecipe([{ op: "gaussian", params: { sigma: 2 } }]);
      }).not.toThrow();

      expect(result).toEqual({ n: 1, persisted: false });
    } finally {
      setItem.mockRestore();
    }
  });

  it("setMacroFromRecipe makes a saved preset replayable as a macro", () => {
    const saved = saveBatchRecipePreset(
      [], "Blur then flip",
      [
        { op: "gaussian", params: { sigma: 2 } },
        { op: "flipv", params: {} },
      ],
    ).saved;
    storeBatchRecipePresets([saved]);

    const preset = loadBatchRecipePresets()[0];
    const { n, persisted } = setMacroFromRecipe(preset.steps);

    expect(n).toBe(2);
    expect(persisted).toBe(true);
    expect(loadMacro()).toEqual([
      { kind: "op", op: "gaussian", params: { sigma: 2 } },
      { kind: "op", op: "flipv", params: {} },
    ]);
  });

  it("a recorded macro's op steps save and re-import as a portable preset", () => {
    startRecording();
    record("/api/filter", { image_id: "a", kind: "gaussian", params: { sigma: 2 } });
    record("/api/filter", { image_id: "a", kind: "crop", params: { row0: 1 } }); // legacy, dropped
    stopRecording();

    const saved = saveBatchRecipePreset([], "From macro", macroOpSteps()).saved;
    const roundTrip = importBatchRecipePreset(
      JSON.stringify({ format: "fermiviewer-batch-preset", version: 1, preset: saved }),
    );
    expect(roundTrip.steps).toEqual([{ op: "gaussian", params: { sigma: 2 } }]);
  });
});
