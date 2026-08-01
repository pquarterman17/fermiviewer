// Keyboard map (handoff §9), split out of App.tsx in the repo-health #33
// decomposition. applyAutoContrast + the keydown effect body moved verbatim;
// the only change is threading the Stage ref through an explicit
// AppHotkeysCtx instead of closing over App's local `stageRef`.

import { useEffect, type RefObject } from "react";

import type { StageHandle } from "../components/Stage/Stage";
import { autoWindow } from "../lib/display";
import { loadPrefs } from "../lib/prefs";
import { renameSingleImage } from "../lib/rename";
import { useStageInfo } from "../store/stage";
import { undoLabel, useViewer, type CaptureMode } from "../store/viewer";

export function applyAutoContrast(): void {
  const s = useViewer.getState();
  const raster = useStageInfo.getState().raster;
  if (s.activeId && raster) {
    const p = loadPrefs();
    s.setDisplay(s.activeId, autoWindow(raster, p.autoLoPct, p.autoHiPct));
  }
}

export interface AppHotkeysCtx {
  stageRef: RefObject<StageHandle | null>;
}

// ── keyboard map (handoff §9) ──
export function useAppHotkeys(ctx: AppHotkeysCtx): void {
  const { stageRef } = ctx;
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      // never hijack keys (Del closing files, sbs ←/→/Tab, capture shortcuts)
      // while a form control or rich-text editor has focus
      if (
        t.tagName === "INPUT" ||
        t.tagName === "TEXTAREA" ||
        t.tagName === "SELECT" ||
        t.isContentEditable
      )
        return;
      // A modal is modal: these shortcuts act on the workspace behind it, and
      // several are destructive (Backspace closes images). aria-modal="true"
      // has to be backed by actually withholding the global map.
      if (document.querySelector('[role="dialog"][aria-modal="true"]')) return;
      const s = useViewer.getState();
      const mod = e.metaKey || e.ctrlKey;

      if (mod && e.key.toLowerCase() === "z") {
        e.preventDefault();
        const entry = e.shiftKey ? s.redo() : s.undo();
        const verb = e.shiftKey ? "redo" : "undo";
        s.setStatus(
          entry ? `${verb}: ${undoLabel(entry)}` : `nothing to ${verb}`,
        );
        return;
      }
      if (mod && e.key.toLowerCase() === "k") {
        e.preventDefault();
        s.setCmdk(!s.cmdk);
        return;
      }
      if (mod && e.key.toLowerCase() === "e") {
        e.preventDefault();
        if (s.activeId) s.setExportOpen(true);
        return;
      }
      if (mod && e.shiftKey && e.key.toLowerCase() === "l") {
        e.preventDefault();
        s.toggleTheme();
        return;
      }
      if (mod && e.key === "[") {
        e.preventDefault();
        s.toggleLeft();
        return;
      }
      if (mod && e.key === "]") {
        e.preventDefault();
        s.toggleRight();
        return;
      }
      if (mod) return; // leave other ⌘/Ctrl chords to the browser
      if (s.cmdk) return; // palette owns the keyboard while open

      // Side-by-side compare: ←/→ step the FOCUSED pane within its bound
      // group (the other panes stay frozen); Tab cycles which pane is focused
      // through the grid. SELECT is excluded so the per-pane dropdowns keep
      // their native arrow nav.
      if (s.compareMode === "sidebyside" && t.tagName !== "SELECT") {
        if (e.key === "ArrowRight") {
          e.preventDefault();
          s.stepPane(s.sbsActive, 1);
          return;
        }
        if (e.key === "ArrowLeft") {
          e.preventDefault();
          s.stepPane(s.sbsActive, -1);
          return;
        }
        if (e.key === "Tab") {
          e.preventDefault();
          const n = s.sbsPanes.length;
          if (n > 0) {
            s.setActivePane((s.sbsActive + (e.shiftKey ? -1 : 1) + n) % n);
          }
          return;
        }
      }

      const capture = (m: CaptureMode) =>
        s.setCaptureMode(s.captureMode === m ? "none" : m);

      switch (e.key) {
        case "?":
          s.setShorts(!s.shorts);
          break;
        case "F2":
          if (s.activeId) void renameSingleImage(s.activeId);
          break;
        case "[":
          s.cycleImage(-1);
          break;
        case "]":
          s.cycleImage(1);
          break;
        case "+":
        case "=":
          stageRef.current?.zoomBy(1.25);
          break;
        case "-":
          stageRef.current?.zoomBy(0.8);
          break;
        case "f":
        case "F":
        case "0":
          stageRef.current?.fit();
          break;
        case "1":
          stageRef.current?.actualSize();
          break;
        case "z":
        case "Z":
          capture("zoom");
          break;
        case "x":
        case "X":
          // zoom-to-dimensions (MATLAB's `d`): place a fixed W×H box and zoom
          capture("fixed-zoom");
          break;
        case "h":
        case "H":
          s.setPanTool(!s.panTool);
          break;
        case "d":
        case "D":
          capture("distance");
          break;
        case "l":
        case "L":
          capture("profile");
          break;
        case "b":
        case "B":
          capture("box-profile");
          break;
        case "g":
        case "G":
          capture("angle");
          break;
        case "p":
        case "P":
          capture("polyline");
          break;
        case "v":
        case "V":
          s.setGalleryOpen(!s.galleryOpen);
          break;
        case "r":
        case "R":
          capture("roi");
          break;
        case "a":
        case "A":
          applyAutoContrast();
          break;
        case "Delete":
        case "Backspace":
          // Precedence: a selected annotation/measure wins (active-editing
          // context); otherwise Del removes the selected file(s) from the
          // library panel. closeImage is session-only — the file on disk
          // stays — so this just unloads, matching the right-click "Close".
          if (s.activeId && s.selectedMulti.length > 0) {
            const prof = useStageInfo.getState().profile;
            for (const mid of s.selectedMulti) {
              s.removeMeasure(s.activeId, mid);
              // clear the dock chart if its profile measure was deleted
              if (prof?.measureId === mid) {
                useStageInfo.getState().setProfile(null);
              }
            }
            s.setSelectedMulti([]);
          } else if (s.activeId && s.selectedMeasure) {
            const sel = s.selectedMeasure;
            s.removeMeasure(s.activeId, sel);
            const prof = useStageInfo.getState().profile;
            if (prof?.measureId === sel) {
              useStageInfo.getState().setProfile(null);
            }
          } else {
            const ids = s.selected.length
              ? [...s.selected]
              : s.activeId
                ? [s.activeId]
                : [];
            // serialize: closeImage is async; closing sequentially avoids the
            // activeId flicker / double-close races of parallel dispatch
            void (async () => {
              for (const id of ids) await s.closeImage(id);
            })().catch((err: Error) => s.setStatus(err.message));
          }
          break;
        case "Escape":
          if (s.compareSet) s.exitCompare();
          s.setCaptureMode("none");
          s.setShorts(false);
          s.setRadial(null);
          s.setSelectedMulti([]);
          break;
        // Arrows cycle through the open files (not pan the image — panning
        // is mouse-drag / the pan tool). ←/↑ previous, →/↓ next; wraps.
        case "ArrowLeft":
        case "ArrowUp":
          s.cycleImage(-1);
          break;
        case "ArrowRight":
        case "ArrowDown":
          s.cycleImage(1);
          break;
        default:
          return;
      }
      e.preventDefault();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
}

