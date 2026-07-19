import { create } from "zustand";

import type { ParamField, ParamValues } from "../lib/params";

type ParamResolver = (value: ParamValues | null) => void;

export interface ParamRequest {
  id: number;
  title: string;
  fields: ParamField[];
  resolve: ParamResolver;
}

interface ParamDialogState {
  /** Pending requests, oldest first. `queue[0]` is the one on screen. */
  queue: ParamRequest[];
  open: (
    title: string,
    fields: ParamField[],
    resolve: ParamResolver,
  ) => void;
  /** Settle the active request and show the next one, if any. */
  submit: (values: ParamValues | null) => void;
  /** Cancel the active request only; queued requests still get their turn. */
  close: () => void;
  /** Settle every pending request with null — teardown, not a user action. */
  cancelAll: () => void;
}

let nextId = 1;

export const useParamDialog = create<ParamDialogState>((set, get) => ({
  queue: [],

  open: (title, fields, resolve) =>
    set((s) => ({
      queue: [...s.queue, { id: nextId++, title, fields, resolve }],
    })),

  // Advance the queue BEFORE resolving: the awaiting caller may synchronously
  // call askParams again, and it must land behind the remaining queue rather
  // than into the slot we are still holding.
  submit: (values) => {
    const active = get().queue[0];
    if (!active) return;
    set((s) => ({ queue: s.queue.slice(1) }));
    active.resolve(values);
  },

  close: () => get().submit(null),

  cancelAll: () => {
    const pending = get().queue;
    if (!pending.length) return;
    set({ queue: [] });
    for (const request of pending) request.resolve(null);
  },
}));

/**
 * Open the lazy dialog view and resolve with typed values or null on cancel.
 *
 * Overlapping calls queue in FIFO order instead of clobbering each other: the
 * previous behaviour replaced the stored resolver, so the earlier promise was
 * orphaned and never settled, hanging its caller forever.
 */
export function askParams(
  title: string,
  fields: ParamField[],
): Promise<ParamValues | null> {
  return new Promise((resolve) => {
    useParamDialog.getState().open(title, fields, resolve);
  });
}
