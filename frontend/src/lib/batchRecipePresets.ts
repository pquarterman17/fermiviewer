import type { BatchRecipeStep } from "./api";

const STORAGE_KEY = "fermiviewer.batchRecipePresets.v1";
const FORMAT = "fermiviewer-batch-preset";

export interface BatchRecipePreset {
  version: 1;
  id: string;
  name: string;
  steps: BatchRecipeStep[];
  createdAt: string;
  updatedAt: string;
}

interface PresetExport {
  format: typeof FORMAT;
  version: 1;
  preset: BatchRecipePreset;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function recipeSteps(value: unknown): BatchRecipeStep[] | null {
  if (!Array.isArray(value) || value.length === 0) return null;
  const steps: BatchRecipeStep[] = [];
  for (const item of value) {
    if (!record(item) || typeof item.op !== "string" || !item.op.trim()) {
      return null;
    }
    if (!record(item.params)) return null;
    steps.push({ op: item.op, params: { ...item.params } });
  }
  return steps;
}

function preset(value: unknown): BatchRecipePreset | null {
  if (
    !record(value) ||
    value.version !== 1 ||
    typeof value.id !== "string" ||
    typeof value.name !== "string" ||
    !value.name.trim() ||
    typeof value.createdAt !== "string" ||
    typeof value.updatedAt !== "string"
  ) {
    return null;
  }
  const steps = recipeSteps(value.steps);
  if (!steps) return null;
  return {
    version: 1,
    id: value.id,
    name: value.name.trim(),
    steps,
    createdAt: value.createdAt,
    updatedAt: value.updatedAt,
  };
}

export function loadBatchRecipePresets(): BatchRecipePreset[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
    if (!Array.isArray(parsed)) return [];
    return parsed
      .map(preset)
      .filter((item): item is BatchRecipePreset => item !== null)
      .sort((a, b) => a.name.localeCompare(b.name));
  } catch {
    return [];
  }
}

export function storeBatchRecipePresets(presets: BatchRecipePreset[]): void {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(presets));
}

export function saveBatchRecipePreset(
  presets: BatchRecipePreset[],
  name: string,
  steps: BatchRecipeStep[],
  replaceId?: string,
  now = new Date().toISOString(),
): { presets: BatchRecipePreset[]; saved: BatchRecipePreset } {
  const cleanName = name.trim();
  const cleanSteps = recipeSteps(steps);
  if (!cleanName) throw new Error("Enter a preset name");
  if (!cleanSteps) throw new Error("Add at least one recipe step");
  const existing = presets.find((item) => item.id === replaceId);
  const saved: BatchRecipePreset = {
    version: 1,
    id: existing?.id ?? crypto.randomUUID(),
    name: cleanName,
    steps: cleanSteps,
    createdAt: existing?.createdAt ?? now,
    updatedAt: now,
  };
  return {
    saved,
    presets: [...presets.filter((item) => item.id !== saved.id), saved].sort(
      (a, b) => a.name.localeCompare(b.name),
    ),
  };
}

export function exportBatchRecipePreset(presetValue: BatchRecipePreset): string {
  const payload: PresetExport = {
    format: FORMAT,
    version: 1,
    preset: presetValue,
  };
  return JSON.stringify(payload, null, 2) + "\n";
}

export function importBatchRecipePreset(text: string): BatchRecipePreset {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch {
    throw new Error("Preset file is not valid JSON");
  }
  if (!record(value) || value.format !== FORMAT || value.version !== 1) {
    throw new Error("This is not a fermiviewer batch preset");
  }
  const imported = preset(value.preset);
  if (!imported) throw new Error("Preset recipe is incomplete or invalid");
  return { ...imported, id: crypto.randomUUID() };
}

export function batchPresetFilename(name: string): string {
  const stem = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
  return `${stem || "batch-recipe"}.fvbatch.json`;
}
