// Desktop shell (handoff §5 <App>): TitleBar / MenuBar / Filmstrip /
// Stage / Inspector / StatusBar grid + the global keyboard map (§9).

import { useEffect, useRef } from "react";

import Inspector from "./components/Inspector/Inspector";
import { listImages } from "./lib/api";
import Filmstrip from "./components/Library/Filmstrip";
import MenuBar from "./components/Shell/MenuBar";
import StatusBar from "./components/Shell/StatusBar";
import TitleBar from "./components/Shell/TitleBar";
import Stage, { type StageHandle } from "./components/Stage/Stage";
import { useViewer } from "./store/viewer";

const NUDGE = 50; // css px per arrow press

export default function App() {
  const stageRef = useRef<StageHandle>(null);
  const leftCol = useViewer((s) => s.leftCol);
  const rightCol = useViewer((s) => s.rightCol);

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

  // ── keyboard map (handoff §9, Phase 1 subset) ──
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA") return;
      const s = useViewer.getState();
      const mod = e.metaKey || e.ctrlKey;

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

      switch (e.key) {
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
          s.setCaptureMode(s.captureMode === "zoom" ? "none" : "zoom");
          break;
        case "h":
        case "H":
          s.setPanTool(!s.panTool);
          break;
        case "Escape":
          s.setCaptureMode("none");
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
        <Stage ref={stageRef} />
        <Inspector />
      </div>
      <StatusBar />
    </div>
  );
}
