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
      }
    | {
        // One level deeper than "rows": a list OF rings, each a row list.
        // `calc.regions.Shape.holes` is a sequence of rings, so a region
        // with two holes cannot be written as "rows" at all.
        kind: "rings";
        width: number | null;
        item_type: string;
        columns: string[];
        min_rings: number;
        max_rings: number | null;
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
  // A region named symbolically ("set_id" or "set_id/region_id"), resolved
  // per image by the runner. Not a param: params.region holds the RESOLVED
  // geometry after substitution, which is what makes a recorded result
  // replayable, while this keeps the name the user wrote.
  region_ref?: string;
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
