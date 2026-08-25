import { beforeEach, describe, expect, it } from "vitest";

import {
  batchPresetFilename,
  exportBatchRecipePreset,
  importBatchRecipePreset,
  loadBatchRecipePresets,
  saveBatchRecipePreset,
  storeBatchRecipePresets,
} from "./batchRecipePresets";

describe("batch recipe presets", () => {
  beforeEach(() => localStorage.clear());

  it("saves, sorts, and reloads recipes", () => {
    const first = saveBatchRecipePreset(
      [],
      "  Level and measure  ",
      [{ op: "plane_level", params: {} }],
      undefined,
      "2026-07-26T12:00:00Z",
    );
    const second = saveBatchRecipePreset(
      first.presets,
      "Analyze noise",
      [{ op: "noise", params: { method: "both" } }],
      undefined,
      "2026-07-26T12:01:00Z",
    );
    storeBatchRecipePresets(second.presets);

    expect(loadBatchRecipePresets().map((item) => item.name)).toEqual([
      "Analyze noise",
      "Level and measure",
    ]);
  });

  it("round-trips a portable versioned preset", () => {
    const saved = saveBatchRecipePreset(
      [],
      "Quantify surfaces",
      [{ op: "roughness", params: { level: "plane" } }],
    ).saved;
    const imported = importBatchRecipePreset(exportBatchRecipePreset(saved));

    expect(imported.id).not.toBe(saved.id);
    expect(imported.name).toBe(saved.name);
    expect(imported.steps).toEqual(saved.steps);
    expect(batchPresetFilename(imported.name)).toBe(
      "quantify-surfaces.fvbatch.json",
    );
  });

  it("preserves portable named inputs and migrates version 1 presets", () => {
    localStorage.setItem(
      "fermiviewer.batchRecipePresets.v1",
      JSON.stringify([{
        version: 1,
        id: "old",
        name: "Subtract reference",
        steps: [{
          op: "image_math",
          params: { op: "subtract" },
          inputs: { other: "reference" },
        }],
        createdAt: "2026-08-24T00:00:00Z",
        updatedAt: "2026-08-24T00:00:00Z",
      }]),
    );

    const loaded = loadBatchRecipePresets()[0];
    expect(loaded.version).toBe(2);
    expect(loaded.steps[0].inputs).toEqual({ other: "reference" });
    expect(JSON.parse(exportBatchRecipePreset(loaded)).version).toBe(2);
  });

  it("rejects unversioned or empty recipes", () => {
    expect(() => importBatchRecipePreset('{"steps":[]}')).toThrow(
      "not a fermiviewer",
    );
    expect(() => saveBatchRecipePreset([], "Empty", [])).toThrow(
      "at least one",
    );
  });
});
