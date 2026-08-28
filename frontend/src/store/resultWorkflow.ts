import { create } from "zustand";

import type { PersistedResultRecord } from "../lib/api";

export type ResultOpenMode = "reopen" | "duplicate";

interface ResultWorkflowState {
  request: { record: PersistedResultRecord; mode: ResultOpenMode; nonce: number } | null;
  open: (record: PersistedResultRecord, mode: ResultOpenMode) => void;
  clear: () => void;
}

/** Ephemeral hand-off from Results & Methods to the originating workshop.
 * It is deliberately not persisted: the saved record remains immutable,
 * while the workshop receives an editable copy of its reproduction key. */
export const useResultWorkflow = create<ResultWorkflowState>((set) => ({
  request: null,
  open: (record, mode) =>
    set((state) => ({ request: { record, mode, nonce: (state.request?.nonce ?? 0) + 1 } })),
  clear: () => set({ request: null }),
}));
