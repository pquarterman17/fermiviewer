// Desktop shell (handoff §5 <App>): MenuBar / Filmstrip / Stage / Inspector /
// StatusBar grid + the global keyboard map (§9) + command palette / shortcuts /
// radial overlays. (The standalone title bar was folded into the menubar.)

import { useEffect, useMemo, useRef } from "react";

import CompareInspector from "./components/Inspector/CompareInspector";
import Inspector from "./components/Inspector/Inspector";
import Filmstrip from "./components/Library/Filmstrip";
import CompactLayout from "./components/Shell/CompactLayout";
import MenuBar from "./components/Shell/MenuBar";
import StatusBar from "./components/Shell/StatusBar";
import ColorbarChip from "./components/Stage/ColorbarChip";
import CompareStage from "./components/Stage/CompareStage";
import SideBySideStage from "./components/Stage/SideBySideStage";
import Stage, { type StageHandle } from "./components/Stage/Stage";
import CommandPalette, { type Action } from "./components/overlays/CommandPalette";
import LazyOverlays from "./components/overlays/LazyOverlays";
import ResultsWindow from "./components/overlays/ResultsWindow";
import RadialMenu from "./components/overlays/RadialMenu";
import TooltipLayer from "./components/overlays/TooltipLayer";
import ToolWindows from "./components/overlays/ToolWindows";
import { useCubeAutoExplore } from "./hooks/useCubeAutoExplore";
import { devSampleFiles, launchDir, listImages } from "./lib/api";
import { COLORMAP_NAMES } from "./lib/colormaps";
import { autoWindow } from "./lib/display";
import { loadPrefs } from "./lib/prefs";
import { renameSingleImage } from "./lib/rename";
import { useStageInfo } from "./store/stage";
import { installErrLog } from "./lib/errlog";
import { undoLabel, useViewer, type CaptureMode } from "./store/viewer";

installErrLog(); // module scope: catch errors from the very first render

function applyAutoContrast(): void {
  const s = useViewer.getState();
  const raster = useStageInfo.getState().raster;
  if (s.activeId && raster) {
    const p = loadPrefs();
    s.setDisplay(s.activeId, autoWindow(raster, p.autoLoPct, p.autoHiPct));
  }
}

export default function App() {
  const stageRef = useRef<StageHandle>(null);
  const leftCol = useViewer((s) => s.leftCol);
  const rightCol = useViewer((s) => s.rightCol);
  const colorbar = useViewer((s) => s.colorbar);
  const colorbarSide = useViewer((s) => s.colorbarSide);
  const comparing = useViewer((s) => s.compareSet !== null);
  const compareMode = useViewer((s) => s.compareMode);

  // EDS cubes open straight into the Spectrum-Image Explorer (not a 4096-
  // channel scroll); the raw channel stepper on the Stage stays available.
  useCubeAutoExplore();

  // restore any prior session (backend keeps images open across reloads)
  useEffect(() => {
    listImages()
      .then((metas) => {
        if (metas.length > 0) {
          // route through ingest so a browser refresh seeds the same
          // per-image state a fresh open does — origin history step (WS4d),
          // tilt + display-pref seeding — instead of hand-rolling a subset
          useViewer.getState().ingest(metas);
          return;
        }
        // Dev testing mode: with an empty session under Vite dev, auto-open
        // a few sample files (jpeg/dm3/dm4/tif) so the load→inspect loop
        // isn't repeated by hand on every restart. The backend keeps the
        // images open across reloads, so this only fires on a fresh server.
        // Opt out with localStorage.fv_dev_autoload="off".
        if (
          import.meta.env.DEV &&
          localStorage.getItem("fv_dev_autoload") !== "off"
        ) {
          devSampleFiles()
            .then((paths) => {
              if (paths.length === 0) return;
              const s = useViewer.getState();
              s.openPaths(paths).catch((e: Error) => s.setStatus(e.message));
            })
            .catch(() => undefined);
        }
      })
      .catch(() => undefined);
  }, []);

  // launch-folder context: when started from a folder of images
  // (`fermiviewer <dir>` / the launch cwd), the Open dialog defaults
  // there. Empty/absent on the installed app — Open stays the OS picker.
  useEffect(() => {
    launchDir()
      .then((ctx) => {
        if (ctx.files.length > 0) useViewer.getState().setLaunchContext(ctx);
      })
      .catch(() => undefined);
  }, []);

  // ── drag-drop open (checklist L) ──
  useEffect(() => {
    const onDragOver = (e: DragEvent) => {
      if (e.dataTransfer?.types.includes("Files")) e.preventDefault();
    };
    const onDrop = (e: DragEvent) => {
      const files = e.dataTransfer?.files;
      if (files && files.length > 0) {
        e.preventDefault();
        const s = useViewer.getState();
        s.openFiles(files).catch((err: Error) => s.setStatus(err.message));
      }
    };
    window.addEventListener("dragover", onDragOver);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragover", onDragOver);
      window.removeEventListener("drop", onDrop);
    };
  }, []);

  // ── follow the OS colour scheme live while the theme choice is "System" ──
  useEffect(() => {
    const mq = window.matchMedia?.("(prefers-color-scheme: light)");
    if (!mq) return;
    const onChange = () => {
      // an explicit dark/light choice is pinned; only "system"/absent follows
      const choice = localStorage.getItem("fv_theme");
      if (choice === "dark" || choice === "light") return;
      useViewer.getState().setTheme("system");
    };
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  // ── trap browser back/forward (mouse back button, ⌫ in old browsers) ──
  // The app is a single-page view with no in-app navigation, so a "back"
  // gesture unloads / "reloads" it (losing transient UI state). Push a
  // sentinel history entry and re-push on every popstate so back/forward
  // can't leave the app. Harmless in the desktop (pywebview/Tauri) shell.
  useEffect(() => {
    history.pushState(null, "", location.href);
    const onPop = () => history.pushState(null, "", location.href);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  // ── keyboard map (handoff §9) ──
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

  // ── command palette action registry ──
  const actions = useMemo<Action[]>(() => {
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

  const mainCls = [
    "fvd-main",
    leftCol ? "left-collapsed" : "",
    rightCol ? "right-collapsed" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="fvd-app">
      <CompactLayout />
      <MenuBar
        onFit={() => stageRef.current?.fit()}
        onActualSize={() => stageRef.current?.actualSize()}
      />
      <div className={mainCls}>
        <Filmstrip />
        <div className="fvd-stage-cell" style={{ flexDirection: (colorbar && colorbarSide === "bottom") ? "column" : undefined }}>
          {colorbar && colorbarSide === "left" && <ColorbarChip />}
          {comparing ? (
            compareMode === "sidebyside" ? (
              <SideBySideStage />
            ) : (
              <CompareStage />
            )
          ) : (
            <Stage ref={stageRef} />
          )}
          {colorbar && colorbarSide === "right" && <ColorbarChip />}
          {colorbar && colorbarSide === "bottom" && <ColorbarChip />}
        </div>
        {comparing ? <CompareInspector /> : <Inspector />}
      </div>
      <StatusBar />
      <TooltipLayer />
      <CommandPalette actions={actions} />
      <RadialMenu />
      <LazyOverlays />
      <ResultsWindow />
      <ToolWindows />
    </div>
  );
}
