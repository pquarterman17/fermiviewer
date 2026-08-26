// Folder-watch client (Scripting #7): start/stop a server-side directory
// poller that auto-runs a saved recipe on new files, plus the status/job
// polling the WatchFolderSection component uses while the dialog is open.

import type { ImageMeta } from "./core";
import type { BatchInputBindings, BatchRecipeStep } from "./batch";
import { json, post } from "./transport";

export interface WatchStatus {
  watching: boolean;
  dir: string | null;
  seen: number;
  processed: number;
  last_error: string | null;
  job_ids: string[];
}

export interface WatchJobResult {
  image_id: string;
  name: string;
  derived: ImageMeta | null;
  values: {
    op: string;
    label: string;
    params: Record<string, unknown>;
    value: Record<string, unknown>;
  }[];
}

export interface WatchJobStatus {
  status: "queued" | "running" | "done" | "error";
  result?: WatchJobResult;
  error?: string;
}

export function startWatch(
  dir: string,
  steps: BatchRecipeStep[],
  interval?: number,
  inputs: BatchInputBindings = {},
): Promise<{ status: string }> {
  return post("/api/watch/start", { dir, steps, interval, inputs });
}

export function stopWatch(): Promise<{ status: string }> {
  return post("/api/watch/stop", {});
}

export async function fetchWatchStatus(): Promise<WatchStatus> {
  return json(await fetch("/api/watch/status"));
}

export async function fetchWatchJob(jobId: string): Promise<WatchJobStatus> {
  return json(await fetch(`/api/jobs/${jobId}`));
}
