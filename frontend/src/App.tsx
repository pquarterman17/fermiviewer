// Desktop shell (handoff §5 <App>): TitleBar / MenuBar / Filmstrip /
// Stage / Inspector / StatusBar grid + the global keyboard map (§9) +
// command palette / shortcuts / radial overlays.

import { useEffect, useMemo, useRef } from "react";

import CompareInspector from "./components/Inspector/CompareInspector";
import Inspector from "./components/Inspector/Inspector";
import Filmstrip from "./components/Library/Filmstrip";
import MenuBar from "./components/Shell/MenuBar";
import StatusBar from "./components/Shell/StatusBar";
import TitleBar from "./components/Shell/TitleBar";
import CompareStage from "./components/Stage/CompareStage";
import Stage, { type StageHandle } from "./components/Stage/Stage";
import CommandPalette, {
  type Action,
} from "./components/overlays/CommandPalette";
import ExportDialog from "./components/overlays/ExportDialog";
import ParamDialog from "./components/overlays/ParamDialog";
import ResultsWindow from "./components/overlays/ResultsWindow";
import RadialMenu from "./components/overlays/RadialMenu";
import ShortcutsOverlay from "./components/overlays/ShortcutsOverlay";
import ToolWindow from "./components/overlays/ToolWindow";
import DiffractionWorkshop from "./components/workshops/DiffractionWorkshop";
import FftMaskWorkshop from "./components/workshops/FftMaskWorkshop";
import EdsWorkshop from "./components/workshops/EdsWorkshop";
import EelsWorkshop from "./components/workshops/EelsWorkshop";
import { listImages } from "./lib/api";
import { COLORMAP_NAMES } from "./lib/colormaps";
import { autoWindow } from "./lib/display";
import { useStageInfo } from "./store/stage";
import { undoLabel, useViewer, type CaptureMode } from "./store/viewer";

const NUDGE = 50; // css px per arrow press

function applyAutoContrast(): void {
  const s = useViewer.getState();
  const raster = useStageInfo.getState().raster;
  if (s.activeId && raster) s.setDisplay(s.activeId, autoWindow(raster));
}

export default function App() {
  const stageRef = useRef<StageHandle>(null);
  const leftCol = useViewer((s) => s.leftCol);
  const rightCol = useViewer((s) => s.rightCol);
  const comparing = useViewer((s) => s.compareSet !== null);
  const tools = useViewer((s) => s.tools);

  // restore any prior session (backend keeps images open across reloads)
  useEffect(() => {
    listImages()
      .then((metas) => {
        if (metas.length === 0) return;
        useViewer.setState((s) => {
          const images = { ...s.images };
          const order = [...s.order];
          for (const m of metas) {
            if (!(m.id in images)) order.push(m.id);
            images[m.id] = m;
          }
          return { images, order, activeId: s.activeId ?? order[0] ?? null };
        });
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

  // ── keyboard map (handoff §9) ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
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

      const capture = (m: CaptureMode) =>
        s.setCaptureMode(s.captureMode === m ? "none" : m);

      switch (e.key) {
        case "?":
          s.setShorts(!s.shorts);
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
        case "g":
        case "G":
          capture("angle");
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
          if (s.activeId && s.selectedMeasure) {
            const sel = s.selectedMeasure;
            s.removeMeasure(s.activeId, sel);
            const prof = useStageInfo.getState().profile;
            if (prof?.measureId === sel) {
              useStageInfo.getState().setProfile(null);
            }
          }
          break;
        case "Escape":
          if (s.compareSet) s.exitCompare();
          s.setCaptureMode("none");
          s.setShorts(false);
          s.setRadial(null);
          break;
        case "ArrowLeft":
          stageRef.current?.nudge(NUDGE, 0);
          break;
        case "ArrowRight":
          stageRef.current?.nudge(-NUDGE, 0);
          break;
        case "ArrowUp":
          stageRef.current?.nudge(0, NUDGE);
          break;
        case "ArrowDown":
          stageRef.current?.nudge(0, -NUDGE);
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
      <TitleBar />
      <MenuBar
        onFit={() => stageRef.current?.fit()}
        onActualSize={() => stageRef.current?.actualSize()}
      />
      <div className={mainCls}>
        <Filmstrip />
        {comparing ? <CompareStage /> : <Stage ref={stageRef} />}
        {comparing ? <CompareInspector /> : <Inspector />}
      </div>
      <StatusBar />
      <CommandPalette actions={actions} />
      <ShortcutsOverlay />
      <RadialMenu />
      <ExportDialog />
      <ParamDialog />
      <ResultsWindow />
      {tools.map((t) => (
        <ToolWindow
          key={t.kind}
          kind={t.kind}
          title={
            {
              eels: "EELS",
              eds: "EDS",
              diffraction: "Diffraction",
              fftmask: "FFT Mask",
            }[t.kind]
          }
          x={t.x}
          y={t.y}
          z={t.z}
          width={t.kind === "diffraction" || t.kind === "fftmask" ? 332 : 360}
        >
          {t.kind === "eels" && <EelsWorkshop />}
          {t.kind === "eds" && <EdsWorkshop />}
          {t.kind === "diffraction" && <DiffractionWorkshop />}
          {t.kind === "fftmask" && <FftMaskWorkshop />}
        </ToolWindow>
      ))}
    </div>
  );
}
