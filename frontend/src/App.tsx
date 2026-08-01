// Desktop shell (handoff §5 <App>): MenuBar / Filmstrip / Stage / Inspector /
// StatusBar grid + the global keyboard map (§9) + command palette / shortcuts /
// radial overlays. (The standalone title bar was folded into the menubar.)

import { useEffect, useRef } from "react";

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
import CommandPalette from "./components/overlays/CommandPalette";
import LazyOverlays from "./components/overlays/LazyOverlays";
import ResultsWindow from "./components/overlays/ResultsWindow";
import RadialMenu from "./components/overlays/RadialMenu";
import TooltipLayer from "./components/overlays/TooltipLayer";
import ToolWindows from "./components/overlays/ToolWindows";
import SpectralModalityPrompt from "./components/overlays/SpectralModalityPrompt";
import { useAppActions } from "./hooks/useAppCommands";
import { useAppHotkeys } from "./hooks/useAppHotkeys";
import { useCubeAutoExplore } from "./hooks/useCubeAutoExplore";
import { devSampleFiles, launchDir, listImages } from "./lib/api";
import { installErrLog } from "./lib/errlog";
import { useViewer } from "./store/viewer";

installErrLog(); // module scope: catch errors from the very first render

export default function App() {
  const stageRef = useRef<StageHandle>(null);
  const leftCol = useViewer((s) => s.leftCol);
  const rightCol = useViewer((s) => s.rightCol);
  const colorbar = useViewer((s) => s.colorbar);
  const colorbarSide = useViewer((s) => s.colorbarSide);
  const comparing = useViewer((s) => s.compareSet !== null);
  const compareMode = useViewer((s) => s.compareMode);

  // Route spectral cubes to EELS/EDS; ambiguous formats get an explicit chooser.
  const cubeAutoExplore = useCubeAutoExplore();

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

  // keyboard map (handoff §9) + command palette action registry — both close
  // over the Stage ref, so they're extracted as ctx-based hooks (repo-health
  // #33 decomposition); see hooks/useAppHotkeys.ts and hooks/useAppCommands.ts.
  useAppHotkeys({ stageRef });
  const actions = useAppActions({ stageRef });

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
      {cubeAutoExplore.pending && (
        <SpectralModalityPrompt
          meta={cubeAutoExplore.pending}
          onChoose={cubeAutoExplore.choose}
          onClose={cubeAutoExplore.dismiss}
        />
      )}
    </div>
  );
}
