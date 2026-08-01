// Command palette action registry, split out of App.tsx in the repo-health
// #33 decomposition. Entries moved verbatim; the only change is threading
// the Stage ref through an explicit AppCommandsCtx instead of closing over
// App's local `stageRef`.

import { useMemo, type RefObject } from "react";

import type { StageHandle } from "../components/Stage/Stage";
import { COLORMAP_NAMES } from "../lib/colormaps";
import type { Action } from "../store/commands";
import { useViewer, type CaptureMode } from "../store/viewer";
import { applyAutoContrast } from "./useAppHotkeys";

export interface AppCommandsCtx {
  stageRef: RefObject<StageHandle | null>;
}

// ── command palette action registry ──
export function useAppActions(ctx: AppCommandsCtx): Action[] {
  const { stageRef } = ctx;
  return useMemo<Action[]>(() => {
    const s = () => useViewer.getState();
    const capture = (m: CaptureMode) => () => s().setCaptureMode(m);
    const acts: Action[] = [
      // View
      {
        id: "fit",
        group: "View",
        label: "Fit image",
        shortcut: "F",
        run: () => stageRef.current?.fit(),
      },
      {
        id: "actual",
        group: "View",
        label: "Actual size (100%)",
        shortcut: "1",
        run: () => stageRef.current?.actualSize(),
      },
      {
        id: "zoom-in",
        group: "View",
        label: "Zoom in",
        shortcut: "+",
        run: () => stageRef.current?.zoomBy(1.25),
      },
      {
        id: "zoom-out",
        group: "View",
        label: "Zoom out",
        shortcut: "−",
        run: () => stageRef.current?.zoomBy(0.8),
      },
      {
        id: "zoom-to-dims",
        group: "View",
        label: "Zoom to dimensions (fixed size)",
        shortcut: "X",
        run: () => s().setCaptureMode("fixed-zoom"),
      },
      {
        id: "theme",
        group: "View",
        label: "Toggle theme",
        shortcut: "⌘⇧L",
        run: () => s().toggleTheme(),
      },
      {
        id: "library",
        group: "View",
        label: "Toggle library panel",
        shortcut: "⌘[",
        run: () => s().toggleLeft(),
      },
      {
        id: "inspector",
        group: "View",
        label: "Toggle inspector panel",
        shortcut: "⌘]",
        run: () => s().toggleRight(),
      },
      // Measure
      {
        id: "distance",
        group: "Measure",
        label: "Measure distance",
        shortcut: "D",
        run: capture("distance"),
      },
      {
        id: "profile",
        group: "Measure",
        label: "Line profile",
        shortcut: "L",
        run: capture("profile"),
      },
      {
        id: "angle",
        group: "Measure",
        label: "Measure angle",
        shortcut: "G",
        run: capture("angle"),
      },
      {
        id: "roi",
        group: "Measure",
        label: "ROI statistics",
        shortcut: "R",
        run: capture("roi"),
      },
      // Adjust
      {
        id: "auto-contrast",
        group: "Adjust",
        label: "Auto contrast",
        shortcut: "A",
        run: applyAutoContrast,
      },
      {
        id: "reset-contrast",
        group: "Adjust",
        label: "Reset contrast",
        run: () => {
          const st = s();
          if (st.activeId) {
            st.setDisplay(st.activeId, { lo: 0, hi: 1, gamma: 1 });
          }
        },
      },
      ...COLORMAP_NAMES.map((name) => ({
        id: `cmap-${name}`,
        group: "Adjust",
        label: `Colormap: ${name}`,
        run: () => {
          const st = s();
          if (st.activeId) st.setDisplay(st.activeId, { cmap: name });
        },
      })),
      // Library
      {
        id: "compare",
        group: "Library",
        label: "Compare selected",
        run: () => {
          const st = s();
          if (st.selected.length >= 2) st.startCompare(st.selected);
        },
      },
      {
        id: "side-by-side",
        group: "Library",
        label: "Side-by-side compare",
        run: () => s().startSideBySide(),
      },
      {
        id: "exit-compare",
        group: "Library",
        label: "Exit compare",
        shortcut: "Esc",
        run: () => s().exitCompare(),
      },
      {
        id: "list-view",
        group: "Library",
        label: "Toggle thumbnails / names",
        run: () => {
          const st = s();
          st.setListView(st.listView === "thumbs" ? "names" : "thumbs");
        },
      },
      {
        id: "next-img",
        group: "Library",
        label: "Next image",
        shortcut: "]",
        run: () => s().cycleImage(1),
      },
      {
        id: "prev-img",
        group: "Library",
        label: "Previous image",
        shortcut: "[",
        run: () => s().cycleImage(-1),
      },
      {
        id: "close-img",
        group: "Library",
        label: "Close image",
        run: () => {
          const st = s();
          if (st.activeId) void st.closeImage(st.activeId);
        },
      },
      {
        id: "export",
        group: "Library",
        label: "Export image…",
        shortcut: "⌘E",
        run: () => {
          if (s().activeId) s().setExportOpen(true);
        },
      },
      // Analyze (workshop windows)
      {
        id: "ws-eels",
        group: "Analyze",
        label: "EELS workshop",
        run: () => s().openTool("eels"),
      },
      {
        id: "ws-eds",
        group: "Analyze",
        label: "EDS workshop",
        run: () => s().openTool("eds"),
      },
      {
        id: "ws-diffraction",
        group: "Analyze",
        label: "Diffraction workshop",
        run: () => s().openTool("diffraction"),
      },
      // Help
      {
        id: "shortcuts",
        group: "Help",
        label: "Keyboard shortcuts",
        shortcut: "?",
        run: () => s().setShorts(true),
      },
    ];
    return acts;
  }, []);
}
