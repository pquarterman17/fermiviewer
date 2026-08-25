import type { ImageMeta } from "./core";
import { runJob } from "./imaging";
import { json, post } from "./transport";

export interface BatchParamSchema {
  name: string;
  type: string;
  default: unknown;
  required: boolean;
  minimum: number | null;
  maximum: number | null;
  choices: unknown[] | null;
  doc: string;
  shape?:
    | {
        kind: "rows";
        width: number;
        item_type: string;
        columns: string[];
        min_rows: number;
        max_rows: number | null;
        allow_none_rows: boolean;
      }
    | {
        kind: "records";
        min_rows: number;
        max_rows: number | null;
        fields: BatchParamSchema[];
      };
}

export interface BatchInputSchema {
  name: string;
  required: boolean;
  variadic: boolean;
  min_count: number | null;
  max_count: number | null;
  kinds: string[] | null;
  doc: string;
}

export interface BatchOperation {
  name: string;
  category: string;
  summary: string;
  produces: "image" | "analysis";
  params: BatchParamSchema[];
  inputs?: BatchInputSchema[];
}

export interface BatchRecipeStep {
  op: string;
  params: Record<string, unknown>;
  inputs?: Record<string, string>;
}

export type BatchInputBindings = Record<string, string | string[]>;

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
  inputs?: BatchInputBindings;
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
  inputs: BatchInputBindings = {},
): Promise<BatchRunResult> {
  return runJob(
    () => post("/api/batch/run", { image_ids: imageIds, steps, inputs }),
    onProgress,
  );
}
