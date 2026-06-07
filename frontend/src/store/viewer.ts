// Single Zustand store — port of the prototype's useFermiViewer() hook
// (handoff §6). Phase 1 slices only; later phases extend this interface.

import { create } from "zustand";

import {
  closeImage as apiClose,
  openSession,
  type ImageMeta,
} from "../lib/api";

/** Per-image view: z = screen px per image px (1 → 100 %),
 *  (px, py) = normalized image point under the viewport centre. */
export interface View {
  z: number;
  px: number;
  py: number;
}

export type CaptureMode = "none" | "zoom"; // Phase 2 adds measure modes
export type Theme = "dark" | "light";

const VIEWS_KEY = "fv_views";

function loadViews(): Record<string, View> {
  try {
    return JSON.parse(localStorage.getItem(VIEWS_KEY) ?? "{}") as Record<
      string,
      View
    >;
  } catch {
    return {};
  }
}

function saveViews(views: Record<string, View>): void {
  localStorage.setItem(VIEWS_KEY, JSON.stringify(views));
}

interface ViewerState {
  // library
  order: string[];
  activeId: string | null;
  images: Record<string, ImageMeta>;
  // per-image view, persisted (localStorage "fv_views")
  views: Record<string, View>;
  // display
  theme: Theme;
  // tools
  captureMode: CaptureMode;
  panTool: boolean;
  // chrome
  leftCol: boolean;
  rightCol: boolean;
  status: string;

  openPaths: (paths: string[]) => Promise<void>;
  setActive: (id: string) => void;
  cycleImage: (dir: 1 | -1) => void;
  closeImage: (id: string) => Promise<void>;
  setView: (id: string, view: View) => void;
  setCaptureMode: (mode: CaptureMode) => void;
  setPanTool: (on: boolean) => void;
  toggleTheme: () => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setStatus: (msg: string) => void;
}

export const useViewer = create<ViewerState>((set, get) => ({
  order: [],
  activeId: null,
  images: {},
  views: loadViews(),
  theme:
    (document.documentElement.getAttribute("data-theme") as Theme) ?? "dark",
  captureMode: "none",
  panTool: false,
  leftCol: false,
  rightCol: false,
  status: "ready",

  openPaths: async (paths) => {
    const metas = await openSession(paths);
    set((s) => {
      const images = { ...s.images };
      const order = [...s.order];
      for (const m of metas) {
        if (!(m.id in images)) order.push(m.id);
        images[m.id] = m;
      }
      const last = metas[metas.length - 1];
      return {
        images,
        order,
        activeId: last ? last.id : s.activeId,
        status: `opened ${metas.length} file${metas.length === 1 ? "" : "s"}`,
      };
    });
  },

  setActive: (id) => set({ activeId: id }),

  cycleImage: (dir) => {
    const { order, activeId } = get();
    if (order.length === 0) return;
    const i = activeId ? order.indexOf(activeId) : 0;
    set({ activeId: order[(i + dir + order.length) % order.length] });
  },

  closeImage: async (id) => {
    await apiClose(id);
    set((s) => {
      const images = { ...s.images };
      delete images[id];
      const order = s.order.filter((o) => o !== id);
      const activeId =
        s.activeId === id ? (order[order.length - 1] ?? null) : s.activeId;
      return { images, order, activeId };
    });
  },

  setView: (id, view) => {
    const views = { ...get().views, [id]: view };
    saveViews(views);
    set({ views });
  },

  setCaptureMode: (mode) => set({ captureMode: mode }),
  setPanTool: (on) => set({ panTool: on }),

  toggleTheme: () => {
    const theme: Theme = get().theme === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", theme);
    set({ theme });
  },

  toggleLeft: () => set((s) => ({ leftCol: !s.leftCol })),
  toggleRight: () => set((s) => ({ rightCol: !s.rightCol })),
  setStatus: (msg) => set({ status: msg }),
}));
