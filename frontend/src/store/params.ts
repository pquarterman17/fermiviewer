import { create } from "zustand";

import type { ParamField, ParamValues } from "../lib/params";

interface ParamDialogState {
  title: string | null;
  fields: ParamField[];
  resolve: ((value: ParamValues | null) => void) | null;
  open: (
    title: string,
    fields: ParamField[],
    resolve: (value: ParamValues | null) => void,
  ) => void;
  close: () => void;
}

export const useParamDialog = create<ParamDialogState>((set) => ({
  title: null,
  fields: [],
  resolve: null,
  open: (title, fields, resolve) => set({ title, fields, resolve }),
  close: () => set({ title: null, fields: [], resolve: null }),
}));

/** Open the lazy dialog view and resolve with typed values or null on cancel. */
export function askParams(
  title: string,
  fields: ParamField[],
): Promise<ParamValues | null> {
  return new Promise((resolve) => {
    useParamDialog.getState().open(title, fields, resolve);
  });
}
