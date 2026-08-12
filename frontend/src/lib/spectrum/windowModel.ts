// One window model over both modalities (SPECTRAL_WORKSPACE_PLAN #2).
//
// EDS has a single signal window with its flanking background inferred;
// EELS has an explicit pre-edge background window plus a signal window.
// This module makes the two shapes interchangeable for the two consumers
// that must not branch on modality:
//
//   - `integrateWindows()` — one readout (net ± σ) whichever model applies,
//     dispatching to the deliberate ports in lib/eds/integrate.ts and
//     lib/eels/integrate.ts;
//   - `dragTargets()` / `applyDrag()` / `nudge()` / `hitTest()` — the item-4
//     editing surface: every window is edges-plus-body, hit-tested in PIXELS
//     (a grab tolerance in energy units would change size with zoom), and
//     dragged through pure functions the gesture layer never has to special-
//     case per modality.

import type { Spectrum } from "../api";
import { integrateWindow, type EdsBackground } from "../eds/integrate";
import {
  integrateEdge,
  type EelsBackgroundMethod,
} from "../eels/integrate";
import {
  orderWindow,
  type EnergyWindow,
  type Modality,
  type SpeciesWindows,
} from "./species";

/** The readout every species row shows, whichever modality produced it. */
export interface WindowReadout {
  net: number;
  sigma: number;
  gross: number;
  /** Estimated background counts under the signal window. */
  background: number;
  /** Channels inside the signal window. */
  channels: number;
  note?: string;
}

export interface IntegrateOptions {
  eds?: { bg?: EdsBackground; e0Kev?: number };
  eels?: { method?: EelsBackgroundMethod };
}

/**
 * Integrate one species' windows against a displayed spectrum. Returns null
 * when the signal window holds no channels (both ports' convention), so the
 * caller renders "no channels" rather than a zero.
 */
export function integrateWindows(
  spec: Spectrum,
  modality: Modality,
  windows: SpeciesWindows,
  opts: IntegrateOptions = {},
): WindowReadout | null {
  const signal = orderWindow(windows.signal);
  if (modality === "eds") {
    const r = integrateWindow(spec, signal.lo, signal.hi, opts.eds?.bg, {
      e0Kev: opts.eds?.e0Kev,
    });
    if (!r) return null;
    return {
      net: r.net,
      sigma: r.sigma,
      gross: r.gross,
      background: r.background,
      channels: r.channels,
      note: r.note,
    };
  }
  const r = integrateEdge(spec, signal, windows.background, opts.eels?.method);
  if (!r) return null;
  return {
    net: r.net,
    sigma: r.sigma,
    gross: r.gross,
    background: r.background_counts,
    channels: r.channels,
    note: r.note,
  };
}

// ── drag targets ──────────────────────────────────────────────────────

/** Which window of the pair a target belongs to. EDS only ever has "signal";
 *  an EELS species adds "background" once that window is set. */
export type WindowKey = "signal" | "background";
export type WindowPart = "lo" | "hi" | "body";

export interface DragTarget {
  window: WindowKey;
  part: WindowPart;
}

/** Every editable target of a window set, in hit-test priority order —
 *  edges before bodies, so a thin window can still be resized. */
export function dragTargets(windows: SpeciesWindows): DragTarget[] {
  const keys: WindowKey[] = windows.background
    ? ["signal", "background"]
    : ["signal"];
  const edges = keys.flatMap<DragTarget>((window) => [
    { window, part: "lo" },
    { window, part: "hi" },
  ]);
  const bodies = keys.map<DragTarget>((window) => ({ window, part: "body" }));
  return [...edges, ...bodies];
}

function windowOf(windows: SpeciesWindows, key: WindowKey): EnergyWindow | null {
  return key === "signal" ? windows.signal : (windows.background ?? null);
}

function withWindow(
  windows: SpeciesWindows,
  key: WindowKey,
  next: EnergyWindow,
): SpeciesWindows {
  return key === "signal"
    ? { ...windows, signal: next }
    : { ...windows, background: next };
}

/**
 * Apply a drag: an edge follows the cursor (the other edge stays), the body
 * slides preserving its span. `grabOffset` is where inside the body the drag
 * started (energy units), so the window doesn't jump to centre on the cursor.
 * Windows may invert mid-drag; the result is always re-ordered.
 */
export function applyDrag(
  windows: SpeciesWindows,
  target: DragTarget,
  energy: number,
  grabOffset = 0,
): SpeciesWindows {
  const w = windowOf(windows, target.window);
  if (!w) return windows;
  if (target.part === "body") {
    const lo = energy - grabOffset;
    return withWindow(windows, target.window, { lo, hi: lo + (w.hi - w.lo) });
  }
  const next =
    target.part === "lo" ? { lo: energy, hi: w.hi } : { lo: w.lo, hi: energy };
  return withWindow(windows, target.window, orderWindow(next));
}

/** Keyboard nudge: slide a whole window by `delta` energy units. */
export function nudge(
  windows: SpeciesWindows,
  key: WindowKey,
  delta: number,
): SpeciesWindows {
  const w = windowOf(windows, key);
  if (!w) return windows;
  return withWindow(windows, key, { lo: w.lo + delta, hi: w.hi + delta });
}

// ── pixel-space hit testing ───────────────────────────────────────────

export interface HitResult extends DragTarget {
  /** Energy offset from the window's lo edge to the grab point — feeds
   *  `applyDrag`'s `grabOffset` for body drags. */
  grabOffset: number;
}

/**
 * Hit-test a cursor position against a window set. `valToPos` maps energy to
 * CSS pixels (uPlot's `u.valToPos(v, "x")`); `posToVal` inverts it. Edges win
 * over bodies, and of two edges within tolerance the nearer wins — dragging
 * a 3-px-wide window must still be able to grab either side.
 */
export function hitTest(
  windows: SpeciesWindows,
  xPx: number,
  valToPos: (v: number) => number,
  posToVal: (px: number) => number,
  tolerancePx = 5,
): HitResult | null {
  let best: HitResult | null = null;
  let bestDist = Infinity;
  for (const target of dragTargets(windows)) {
    const w = windowOf(windows, target.window);
    if (!w) continue;
    if (target.part === "body") {
      if (best) continue; // an edge already claimed it
      const loPx = valToPos(w.lo);
      const hiPx = valToPos(w.hi);
      if (xPx > Math.min(loPx, hiPx) && xPx < Math.max(loPx, hiPx)) {
        return { ...target, grabOffset: posToVal(xPx) - w.lo };
      }
      continue;
    }
    const edgePx = valToPos(target.part === "lo" ? w.lo : w.hi);
    const dist = Math.abs(xPx - edgePx);
    if (dist <= tolerancePx && dist < bestDist) {
      best = { ...target, grabOffset: 0 };
      bestDist = dist;
    }
  }
  return best;
}

/** The cursor a hit should show: resize arrows on edges, a grab hand on the
 *  body — the affordance is the discoverability of the whole feature. */
export function cursorFor(hit: HitResult | null): string {
  if (!hit) return "";
  return hit.part === "body" ? "grab" : "ew-resize";
}
