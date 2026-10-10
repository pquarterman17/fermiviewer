// Opened AFM force-curve files (routes/afm_force.py) and which one the
// Force Curves workshop shows. Standalone like store/folderImportNotice.ts:
// force files are not images, so they stay out of the viewer store.
import { create } from "zustand";

import { closeForceFile, listForceFiles, type ForceMeta } from "../lib/api";

interface AfmForceState {
  files: ForceMeta[];
  selectedId: string | null;
  error: string | null;
  /** Re-list from the server (files can arrive by folder import too). */
  refresh: () => Promise<void>;
  /** Files an open just returned: listed, the last one selected. */
  adopt: (metas: ForceMeta[]) => void;
  select: (id: string) => void;
  close: (id: string) => Promise<void>;
}

export const useAfmForce = create<AfmForceState>((set, get) => ({
  files: [],
  selectedId: null,
  error: null,
  refresh: async () => {
    try {
      const files = await listForceFiles();
      const keep = files.some((f) => f.id === get().selectedId);
      set({
        files,
        error: null,
        selectedId: keep ? get().selectedId : (files.at(-1)?.id ?? null),
      });
    } catch (e) {
      set({ error: (e as Error).message });
    }
  },
  adopt: (metas) => {
    if (!metas.length) return;
    const known = new Set(get().files.map((f) => f.id));
    set({
      files: [...get().files, ...metas.filter((m) => !known.has(m.id))],
      selectedId: metas[metas.length - 1].id,
    });
  },
  select: (id) => set({ selectedId: id }),
  close: async (id) => {
    await closeForceFile(id);
    const files = get().files.filter((f) => f.id !== id);
    set({
      files,
      selectedId: get().selectedId === id ? (files.at(-1)?.id ?? null) : get().selectedId,
    });
  },
}));
