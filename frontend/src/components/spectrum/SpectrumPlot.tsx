// Shared spectrum plot (uPlot): x-zoom, one or two draggable energy windows,
// element-coloured markers, and optional fit-curve overlays. Used by both the
// EDS Explore tab (signal window only) and the EELS Explore tab (signal +
// pre-edge background window) — SPECTRAL_WORKSPACE_PLAN #13 generalises what
// had been an EDS-only component.
//
// Gesture split (EdsSpectrumZoomBar carries the visible affordances):
//   drag         → zoom the energy axis (uPlot's native drag-select)
//   drag window edge / body → resize / slide a window
//                  (claimed in spectrumWindowGestures.ts before uPlot's zoom)
//   shift + drag → set the signal window from scratch
//   wheel        → zoom about the energy under the cursor
//   double-click → reset to the full range (uPlot native)
//   ← / →        → nudge the SIGNAL window one channel (shift: ten), plot
//                  focused — the background window has no keyboard nudge,
//                  matching spectrumWindowGestures.ts's `nudge(..., "signal", …)`
//
// The window handler previously bound mousedown/mouseup to the <canvas>. uPlot
// builds its wrap as under → canvas → over, and `.u-over` is absolutely
// positioned across the plot area, so those events landed on `.u-over` and
// bubbled to the wrapper — never reaching the sibling canvas. The window drag
// therefore only fired in the axis gutters, where `offsetX - bbox.left` also
// mixed CSS pixels with uPlot's device-pixel bbox. Both are fixed here by going
// through `u.over` and uPlot's own select machinery.
//
// The window/marker overlay reads refs inside the `draw` hook instead of
// listing eLo/eHi/background/markers as build-effect dependencies, so dragging
// a window or recolouring an element redraws the live chart rather than
// destroying and rebuilding it on every frame. `overlays` (fit curves) is the
// one exception: it rebuilds the plot, because a new series list needs a new
// uPlot instance and fit curves change on button click, not on every frame.
//
// Two callback shapes coexist for back-compat: `onDragWindow`/`onDragWindowLive`
// (single signal window, energy pair) is the original EDS contract and its
// behaviour is unchanged when `background` is absent; `onDragWindowsLive`/
// `onDragWindowsCommit` (full `SpeciesWindows`) is the new shape that also
// reports the background window when present. Both fire together on every
// signal-window change, so an EDS caller supplying only the old prop keeps
// working untouched.

import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import uPlot from "uplot";

import type { Spectrum } from "../../lib/api";
import { useElementColors } from "../../lib/elemental/elementColors";
import type { PeakMarker } from "../../lib/eds/peakMarkers";
import type { EnergyWindow, SpeciesWindows } from "../../lib/spectrum/species";
import { zoomAbout, type XRange } from "../../lib/spectrum/zoomRange";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import PlotContextSurface from "../plots/PlotContextSurface";
import { attachWindowGestures } from "./spectrumWindowGestures";

const WHEEL_STEP = 1.25;

/** Extra y-series drawn on the same energy axis (a fit's background/signal
 *  curves). Kept separate from `markers` because these are full arrays that
 *  warrant a real uPlot series rather than a canvas overlay line. */
export interface SpectrumOverlay {
  label: string;
  values: number[];
  color: string;
  dash?: number[];
}

/** Stable default for `overlays`. A `= []` default parameter would mint a
 *  fresh array every render, and `overlays` sits in the build effect's
 *  dependency array — so every parent re-render (INCLUDING every live drag
 *  frame, which sets parent state) would destroy and rebuild the uPlot,
 *  tearing down the drag session mid-gesture. Same defect class as the
 *  zustand stable-snapshot rule; callers that do pass overlays must pass a
 *  memoized array for the same reason (EelsExploreTab useMemo's its). */
const NO_OVERLAYS: SpectrumOverlay[] = [];

export default function SpectrumPlot({
  spec,
  label,
  eLo,
  eHi,
  onDragWindow,
  markers = [],
  height = 260,
  logScale = false,
  onExportCsv,
  xRange = null,
  minSpan = 0,
  onXRangeChange,
  onDragWindowLive,
  background = null,
  onDragWindowsLive,
  onDragWindowsCommit,
  overlays = NO_OVERLAYS,
}: {
  spec: Spectrum;
  label: string;
  eLo: number;
  eHi: number;
  /** Committed signal-window change — release of a drag/nudge, or a
   *  shift-drag. Optional so a caller driving purely off `onDragWindowsCommit`
   *  (EELS, once both windows matter) need not supply a redundant handler. */
  onDragWindow?: (lo: number, hi: number) => void;
  /** Streaming signal-window change while a drag/nudge is live. Client-side
   *  readouts only; the commit callback is where to refetch. */
  onDragWindowLive?: (lo: number, hi: number) => void;
  markers?: PeakMarker[];
  height?: number;
  logScale?: boolean;
  onExportCsv?: () => void;
  /** Controlled energy view; null shows the full spectrum. */
  xRange?: XRange | null;
  /** Narrowest view the wheel may zoom to, in the spectrum's energy units. */
  minSpan?: number;
  /** Accepts an updater so successive wheel steps compose even when several
   *  land in one render — a fast trackpad flick otherwise loses steps that
   *  all zoomed from the same stale prop. */
  onXRangeChange?: Dispatch<SetStateAction<XRange | null>>;
  /** Second draggable window (EELS pre-edge background), painted amber. Absent
   *  or null renders/drags exactly one window — the original EDS shape. */
  background?: EnergyWindow | null;
  /** Streaming/committed change reported as the FULL window set, whichever
   *  window (signal or background) moved. Fires alongside the single-window
   *  callbacks above, never instead of them. */
  onDragWindowsLive?: (windows: SpeciesWindows) => void;
  onDragWindowsCommit?: (windows: SpeciesWindows) => void;
  /** Extra curves on the same energy axis (e.g. a background/signal fit).
   *  Changing this rebuilds the plot — see the header comment. */
  overlays?: SpectrumOverlay[];
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const shiftDragRef = useRef(false);
  const elementColors = useElementColors();

  // Live inputs the plot's own handlers and draw hook read. Assigning on every
  // render keeps them current without making them build-effect dependencies.
  const live = useRef({
    eLo,
    eHi,
    background,
    markers,
    elementColors,
    xRange,
    minSpan,
  });
  live.current = { eLo, eHi, background, markers, elementColors, xRange, minSpan };
  const callbacks = useRef({
    onDragWindow,
    onDragWindowLive,
    onXRangeChange,
    onDragWindowsLive,
    onDragWindowsCommit,
  });
  callbacks.current = {
    onDragWindow,
    onDragWindowLive,
    onXRangeChange,
    onDragWindowsLive,
    onDragWindowsCommit,
  };

  // A window-set change, reported through both callback shapes at once.
  const windowsOf = (signal: EnergyWindow): SpeciesWindows =>
    live.current.background
      ? { signal, background: live.current.background }
      : { signal };
  const dispatchLive = (w: SpeciesWindows) => {
    callbacks.current.onDragWindowLive?.(w.signal.lo, w.signal.hi);
    callbacks.current.onDragWindowsLive?.(w);
  };
  const dispatchCommit = (w: SpeciesWindows) => {
    callbacks.current.onDragWindow?.(w.signal.lo, w.signal.hi);
    callbacks.current.onDragWindowsCommit?.(w);
  };

  useEffect(() => {
    const host = hostRef.current;
    if (!host || spec.energy.length === 0) return;
    plotRef.current?.destroy();

    const energy = spec.energy as unknown as number[];
    const bounds: XRange = [energy[0], energy[energy.length - 1]];
    const initial = live.current.xRange;

    const seriesConfig: uPlot.Series[] = [
      { label: `E (${spec.units})` },
      {
        label: logScale ? "log₁₀(counts + 1)" : "Counts",
        stroke: "#8b5cf6",
        width: 1,
        points: { show: false },
      },
    ];
    const alignedData: unknown[] = [
      energy,
      (logScale
        ? spec.counts.map((v) => Math.log10(Math.max(0, v) + 1))
        : spec.counts) as unknown as number[],
    ];
    for (const overlay of overlays) {
      seriesConfig.push({
        label: overlay.label,
        stroke: overlay.color,
        width: 1.25,
        ...(overlay.dash ? { dash: overlay.dash } : {}),
      });
      alignedData.push(overlay.values);
    }

    const u = new uPlot(
      {
        width: host.clientWidth || 320,
        height,
        title: label,
        // energy axis is keV/eV, not a timestamp — uPlot defaults x to a time
        // scale, which renders small values as clock/date labels
        scales: {
          x: {
            time: false,
            ...(initial ? { min: initial[0], max: initial[1] } : {}),
          },
        },
        series: seriesConfig,
        axes: [
          { stroke: "#888", grid: { stroke: "rgba(128,128,128,0.15)" } },
          {
            stroke: "#888",
            grid: { stroke: "rgba(128,128,128,0.15)" },
            size: 64,
            values: (_u, ticks) => ticks.map(formatCountTick),
          },
        ],
        legend: { show: true },
        cursor: { y: false },
        hooks: {
          setSelect: [
            (u2) => {
              // Only claim the gesture the user started with shift held; a
              // plain drag falls through to uPlot's own zoom.
              if (!shiftDragRef.current) return;
              shiftDragRef.current = false;
              const { left, width } = u2.select;
              if (width > 1) {
                const lo = u2.posToVal(left, "x");
                const hi = u2.posToVal(left + width, "x");
                dispatchCommit(windowsOf({ lo, hi }));
              }
              // uPlot only auto-hides the selection on the zoom path, which
              // this gesture deliberately suppressed.
              u2.setSelect({ left: 0, top: 0, width: 0, height: 0 }, false);
            },
          ],
          setScale: [
            (u2, key) => {
              if (key !== "x") return;
              const { min, max } = u2.scales.x;
              if (min == null || max == null) return;
              const isFull =
                min <= bounds[0] + 1e-12 && max >= bounds[1] - 1e-12;
              callbacks.current.onXRangeChange?.(isFull ? null : [min, max]);
            },
          ],
          draw: [
            (u2) => {
              const {
                eLo: lo,
                eHi: hi,
                background: bg,
                markers: marks,
                elementColors: color,
              } = live.current;
              const ctx = u2.ctx;
              const y0 = u2.bbox.top;
              const y1 = u2.bbox.top + u2.bbox.height;

              const paintWindow = (
                winLo: number,
                winHi: number,
                fill: string,
                stroke: string,
              ) => {
                const x0 = u2.valToPos(winLo, "x") + u2.bbox.left;
                const x1 = u2.valToPos(winHi, "x") + u2.bbox.left;
                ctx.save();
                ctx.globalAlpha = 0.15;
                ctx.fillStyle = fill;
                ctx.fillRect(x0, y0, x1 - x0, y1 - y0);
                ctx.globalAlpha = 1;
                ctx.strokeStyle = stroke;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                ctx.moveTo(x0, y0);
                ctx.lineTo(x0, y1);
                ctx.moveTo(x1, y0);
                ctx.lineTo(x1, y1);
                ctx.stroke();
                ctx.restore();
              };

              paintWindow(lo, hi, "#3b82f6", "#2563eb"); // signal
              if (bg) paintWindow(bg.lo, bg.hi, "#d97706", "#b45309"); // background (EELS pre-edge)

              // characteristic-line / edge-onset labels: each in its
              // element's registry colour, so a marker, its composite
              // channel and its map tint all read as the same element.
              // Auto-detected peaks stay dashed and desaturated.
              for (const m of marks) {
                const mx = u2.valToPos(m.energyKev, "x") + u2.bbox.left;
                if (mx < u2.bbox.left || mx > u2.bbox.left + u2.bbox.width)
                  continue;
                const accent =
                  m.kind === "selected" ? color(m.symbol) : "#9ca3af";
                ctx.save();
                ctx.strokeStyle = accent;
                ctx.lineWidth = m.kind === "selected" ? 1.5 : 1;
                ctx.setLineDash(m.kind === "selected" ? [] : [3, 3]);
                ctx.beginPath();
                ctx.moveTo(mx, y0);
                ctx.lineTo(mx, y1);
                ctx.stroke();
                ctx.setLineDash([]);
                ctx.fillStyle = m.kind === "selected" ? accent : "#6b7280";
                ctx.font = "9px sans-serif";
                ctx.translate(mx + 2, y0 + 2);
                ctx.rotate(Math.PI / 2);
                ctx.fillText(m.label, 0, 0);
                ctx.restore();
              }
            },
          ],
        },
      } satisfies uPlot.Options,
      alignedData as unknown as uPlot.AlignedData,
      host,
    );
    plotRef.current = u;

    const over = u.over;
    const onDown = (e: MouseEvent) => {
      shiftDragRef.current = e.shiftKey;
      // uPlot reads cursor.drag.setScale at mouseup, *after* the setSelect
      // hook runs, so the flag is restored on the next mousedown rather than
      // in the hook — restoring it there would let the window drag also zoom.
      if (u.cursor.drag) u.cursor.drag.setScale = !e.shiftKey;
    };
    const onWheel = (e: WheelEvent) => {
      if (!over || e.deltaY === 0) return;
      e.preventDefault();
      const anchor = u.posToVal(
        e.clientX - over.getBoundingClientRect().left,
        "x",
      );
      const factor = e.deltaY < 0 ? 1 / WHEEL_STEP : WHEEL_STEP;
      const minimum = live.current.minSpan;
      callbacks.current.onXRangeChange?.((prev) =>
        zoomAbout(prev, bounds, anchor, factor, minimum),
      );
    };
    over?.addEventListener("mousedown", onDown);
    over?.addEventListener("wheel", onWheel, { passive: false });

    // Direct manipulation of the energy window(s) (edges resize, body slides,
    // arrows nudge the signal window). Live updates stream to the cheap
    // client-side readout; the commit lands on the same callbacks a
    // shift-drag uses.
    const detachGestures = over
      ? attachWindowGestures(u, host, {
          getWindows: () =>
            windowsOf({ lo: live.current.eLo, hi: live.current.eHi }),
          onLive: dispatchLive,
          onCommit: dispatchCommit,
          nudgeStep: () =>
            energy.length > 1
              ? (energy[energy.length - 1] - energy[0]) / (energy.length - 1)
              : 0,
        })
      : undefined;

    const ro = new ResizeObserver(() => {
      if (host.clientWidth > 0) u.setSize({ width: host.clientWidth, height });
    });
    ro.observe(host);
    return () => {
      ro.disconnect();
      detachGestures?.();
      over?.removeEventListener("mousedown", onDown);
      over?.removeEventListener("wheel", onWheel);
      u.destroy();
      plotRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [spec, label, height, logScale, overlays]);

  // Apply an externally-driven view (zoom bar, pinned region, wheel). A change
  // that originated inside uPlot already matches, so this is a no-op for it and
  // the scale/state round trip cannot oscillate.
  useEffect(() => {
    const u = plotRef.current;
    if (!u?.scales?.x || spec.energy.length === 0) return;
    const [lo, hi] = xRange ?? [
      spec.energy[0],
      spec.energy[spec.energy.length - 1],
    ];
    if (u.scales.x.min === lo && u.scales.x.max === hi) return;
    u.setScale("x", { min: lo, max: hi });
  }, [xRange, spec]);

  // Overlay-only inputs: repaint the existing canvas, never rebuild the plot.
  useEffect(() => {
    plotRef.current?.redraw?.(false);
  }, [eLo, eHi, background, markers, elementColors]);

  return (
    <PlotContextSurface
      ref={hostRef}
      plotRef={plotRef}
      label={label}
      filename="eds-spectrum.png"
      onExportData={onExportCsv}
      exportLabel="Export spectrum CSV"
      className="fvd-ws-plot fvd-eds-spectrum-plot"
      style={{ minHeight: height + 20 }}
    />
  );
}
