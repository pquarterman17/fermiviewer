import type { ImageMeta } from "./core";
import { runJob } from "./imaging";
import { json, post } from "./transport";

export interface BatchParamSchema {
  name: string;
  type: "float" | "int" | "str" | "bool";
  default: unknown;
  required: boolean;
  minimum: number | null;
  maximum: number | null;
  choices: unknown[] | null;
  doc: string;
}

export interface BatchOperation {
  name: string;
  category: string;
  summary: string;
  produces: "image" | "analysis";
  params: BatchParamSchema[];
}

export interface BatchRecipeStep {
  op: string;
  params: Record<string, unknown>;
}

export interface BatchValueResult {
  op: string;
  label: string;
  params: Record<string, unknown>;
  value: Record<string, unknown>;
}

export interface BatchOutput {
  image_id: string;
  name: string;
  status: "done" | "error";
  error?: string;
  derived: ImageMeta | null;
  values: BatchValueResult[];
}

export interface BatchRunResult {
  version: number;
  steps: BatchRecipeStep[];
  outputs: BatchOutput[];
  succeeded: number;
  failed: number;
}

export async function fetchBatchOperations(): Promise<BatchOperation[]> {
  const result = await json<{ version: number; operations: BatchOperation[] }>(
    await fetch("/api/batch/operations"),
  );
  return result.operations;
}

export function runBatchRecipe(
  imageIds: string[],
  steps: BatchRecipeStep[],
  onProgress: (fraction: number, message: string) => void,
): Promise<BatchRunResult> {
  return runJob(
    () => post("/api/batch/run", { image_ids: imageIds, steps }),
    onProgress,
  );
}
