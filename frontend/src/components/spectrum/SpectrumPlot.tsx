// EDS spectrum plot (uPlot): x-zoom, a shift-drag energy window, and
// element-coloured characteristic-line markers.
//
// Gesture split (EdsSpectrumZoomBar carries the visible affordances):
//   drag         → zoom the energy axis (uPlot's native drag-select)
//   drag window edge / body → resize / slide the energy window
//                  (claimed in spectrumWindowGestures.ts before uPlot's zoom)
//   shift + drag → set the element-map energy window
//   wheel        → zoom about the energy under the cursor
//   double-click → reset to the full range (uPlot native)
//   ← / →        → nudge the window one channel (shift: ten), plot focused
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
// listing eLo/eHi/markers as build-effect dependencies, so dragging the window
// or recolouring an element redraws the live chart rather than destroying and
// rebuilding it on every frame.

import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import uPlot from "uplot";

import type { Spectrum } from "../../lib/api";
import { useElementColors } from "../../lib/elemental/elementColors";
import type { PeakMarker } from "../../lib/eds/peakMarkers";
import { zoomAbout, type XRange } from "../../lib/spectrum/zoomRange";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import PlotContextSurface from "../plots/PlotContextSurface";
import { attachWindowGestures } from "./spectrumWindowGestures";

const WHEEL_STEP = 1.25;

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
}: {
  spec: Spectrum;
  label: string;
  eLo: number;
  eHi: number;
  /** Committed window change — release of a drag/nudge, or a shift-drag. */
  onDragWindow: (lo: number, hi: number) => void;
  /** Streaming window change while an edge/body drag or key-nudge is live.
   *  Client-side readouts only; the commit callback is where to refetch. */
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
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const plotRef = useRef<uPlot | null>(null);
  const shiftDragRef = useRef(false);
  const elementColors = useElementColors();

  // Live inputs the plot's own handlers and draw hook read. Assigning on every
  // render keeps them current without making them build-effect dependencies.
  const live = useRef({ eLo, eHi, markers, elementColors, xRange, minSpan });
  live.current = { eLo, eHi, markers, elementColors, xRange, minSpan };
  const callbacks = useRef({ onDragWindow, onDragWindowLive, onXRangeChange });
  callbacks.current = { onDragWindow, onDragWindowLive, onXRangeChange };

  useEffect(() => {
    const host = hostRef.current;
    if (!host || spec.energy.length === 0) return;
    plotRef.current?.destroy();

    const energy = spec.energy as unknown as number[];
    const bounds: XRange = [energy[0], energy[energy.length - 1]];
    const initial = live.current.xRange;

    const u = new uPlot(
      {
        width: host.clientWidth || 320,
        height,
        title: label,
        // energy axis is keV, not a timestamp — uPlot defaults x to a time
        // scale, which renders small keV values as clock/date labels
        scales: {
          x: {
            time: false,
            ...(initial ? { min: initial[0], max: initial[1] } : {}),
          },
        },
        series: [
          { label: `E (${spec.units})` },
          {
            label: logScale ? "log₁₀(counts + 1)" : "Counts",
            stroke: "#8b5cf6",
            width: 1,
            points: { show: false },
          },
        ],
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
                callbacks.current.onDragWindow(
                  u2.posToVal(left, "x"),
                  u2.posToVal(left + width, "x"),
                );
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
              const { eLo: lo, eHi: hi, markers: marks, elementColors: color } =
                live.current;
              const ctx = u2.ctx;
              const x0 = u2.valToPos(lo, "x");
              const x1 = u2.valToPos(hi, "x");
              const y0 = u2.bbox.top;
              const y1 = u2.bbox.top + u2.bbox.height;
              ctx.save();
              ctx.globalAlpha = 0.15;
              ctx.fillStyle = "#3b82f6";
              ctx.fillRect(x0 + u2.bbox.left, y0, x1 - x0, y1 - y0);
              ctx.globalAlpha = 1;
              ctx.strokeStyle = "#2563eb";
              ctx.lineWidth = 1.5;
              ctx.beginPath();
              ctx.moveTo(x0 + u2.bbox.left, y0);
              ctx.lineTo(x0 + u2.bbox.left, y1);
              ctx.moveTo(x1 + u2.bbox.left, y0);
              ctx.lineTo(x1 + u2.bbox.left, y1);
              ctx.stroke();
              ctx.restore();

              // characteristic-line / peak labels (Si Kα, Fe Kα, …): each in
              // its element's registry colour, so a marker, its composite
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
      [
        energy,
        (logScale
          ? spec.counts.map((v) => Math.log10(Math.max(0, v) + 1))
          : spec.counts) as unknown as number[],
      ] as uPlot.AlignedData,
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

    // Direct manipulation of the energy window (edges resize, body slides,
    // arrows nudge). Live updates stream to the cheap client-side readout;
    // the commit lands on the same callback a shift-drag uses.
    const detachGestures = over
      ? attachWindowGestures(u, host, {
          getWindows: () => ({
            signal: { lo: live.current.eLo, hi: live.current.eHi },
          }),
          onLive: (w) =>
            callbacks.current.onDragWindowLive?.(w.signal.lo, w.signal.hi),
          onCommit: (w) =>
            callbacks.current.onDragWindow(w.signal.lo, w.signal.hi),
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
  }, [spec, label, height, logScale]);

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
  }, [eLo, eHi, markers, elementColors]);

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
