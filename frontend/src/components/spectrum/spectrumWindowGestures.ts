// Direct-manipulation editing of the spectrum's energy window
// (SPECTRAL_WORKSPACE_PLAN #4): grab an edge to resize, the middle to slide,
// arrow keys to nudge. Pure decisions (hit-testing, drag math) live in
// lib/spectrum/windowModel.ts; this module is only the DOM wiring around one
// uPlot instance.
//
// Gesture precedence — the existing plot gestures must keep working:
//   - the claim runs as a CAPTURE-phase mousedown on the plot's host element.
//     uPlot binds its zoom-select mousedown directly on `.u-over`, and
//     same-element listeners fire in registration order, so a listener on
//     `.u-over` itself can never pre-empt it. An ancestor's capture phase
//     runs before anything at the target; stopPropagation() there is what
//     keeps a claimed edge-drag from also starting a zoom.
//   - shift-drag (draw a new window) and right/middle buttons are never
//     claimed, and a plain drag that hits neither an edge nor the window
//     body falls through to uPlot's zoom untouched.
//
// Live vs commit: onLive fires every frame (the client-side readout is
// cheap); onCommit fires once on release / key-up, which is where the caller
// refetches the element map. Keyboard nudge commits on key-up so holding an
// arrow key streams live updates but requests one map.

import type { SpeciesWindows } from "../../lib/spectrum/species";
import {
  applyDrag,
  cursorFor,
  hitTest,
  nudge,
  type HitResult,
} from "../../lib/spectrum/windowModel";

/** The slice of uPlot this module drives. */
export interface WindowGesturePlot {
  over: HTMLElement;
  posToVal(px: number, scale: "x"): number;
  valToPos(v: number, scale: "x"): number;
}

export interface WindowGestureOptions {
  getWindows(): SpeciesWindows;
  onLive(windows: SpeciesWindows): void;
  onCommit(windows: SpeciesWindows): void;
  /** Fine keyboard step in energy units (one channel); shift multiplies. */
  nudgeStep(): number;
  tolerancePx?: number;
}

const COARSE = 10;

export function attachWindowGestures(
  u: WindowGesturePlot,
  host: HTMLElement,
  opts: WindowGestureOptions,
): () => void {
  const tolerance = opts.tolerancePx ?? 5;
  const { over } = u;
  if (host.tabIndex < 0) host.tabIndex = 0;

  let session: { hit: HitResult; last: SpeciesWindows } | null = null;
  let keyed: SpeciesWindows | null = null; // latest keyboard-nudged state

  const xOf = (e: MouseEvent) => e.clientX - over.getBoundingClientRect().left;
  const toPx = (v: number) => u.valToPos(v, "x");
  const toVal = (px: number) => u.posToVal(px, "x");

  const onMove = (e: MouseEvent) => {
    if (!session) return;
    const next = applyDrag(
      session.last,
      session.hit,
      toVal(xOf(e)),
      session.hit.grabOffset,
    );
    session.last = next;
    opts.onLive(next);
  };

  const onUp = () => {
    if (!session) return;
    const { last } = session;
    session = null;
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
    over.style.cursor = "";
    opts.onCommit(last);
  };

  const onDown = (e: MouseEvent) => {
    // Never claim modified or non-primary presses: shift-drag draws a new
    // window, right-click opens the plot menu, and uPlot owns the rest.
    if (e.button !== 0 || e.shiftKey || e.ctrlKey || e.altKey || e.metaKey)
      return;
    const target = e.target as Node;
    if (target !== over && !over.contains(target)) return; // axes, title…
    const hit = hitTest(opts.getWindows(), xOf(e), toPx, toVal, tolerance);
    if (!hit) return; // fall through to uPlot's zoom
    e.stopPropagation();
    e.preventDefault();
    host.focus();
    session = { hit, last: opts.getWindows() };
    over.style.cursor = hit.part === "body" ? "grabbing" : "ew-resize";
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  };

  const onHover = (e: MouseEvent) => {
    if (session) return;
    const hit = hitTest(opts.getWindows(), xOf(e), toPx, toVal, tolerance);
    over.style.cursor = cursorFor(hit);
  };

  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    e.preventDefault();
    e.stopPropagation(); // the app's global hotkeys also use arrows
    const step = opts.nudgeStep() * (e.shiftKey ? COARSE : 1);
    const delta = e.key === "ArrowLeft" ? -step : step;
    keyed = nudge(keyed ?? opts.getWindows(), "signal", delta);
    opts.onLive(keyed);
  };

  const onKeyUp = (e: KeyboardEvent) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    if (!keyed) return;
    const last = keyed;
    keyed = null;
    opts.onCommit(last);
  };

  host.addEventListener("mousedown", onDown, true);
  over.addEventListener("mousemove", onHover);
  host.addEventListener("keydown", onKeyDown);
  host.addEventListener("keyup", onKeyUp);
  return () => {
    host.removeEventListener("mousedown", onDown, true);
    over.removeEventListener("mousemove", onHover);
    host.removeEventListener("keydown", onKeyDown);
    host.removeEventListener("keyup", onKeyUp);
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  };
}
