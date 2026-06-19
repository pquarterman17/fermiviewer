// Surface plot (checklist K): interactive 3D orbit + colormap + colorbar.
// Renders on canvas 2D via a parallel-projection mesh (avoids WebGL/StrictMode
// pitfalls). Drag to orbit (azimuth/elevation); colormap driven by the
// active image's display.cmap; colorbar shows z-min … z-max in image units.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { buildLut } from "../../lib/colormaps";
import {
  DEFAULT_AZ,
  DEFAULT_EL,
  clampEl,
  dragToOrbit,
  normaliseAz,
  project,
} from "../../lib/surface3d";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY, useViewer } from "../../store/viewer";

// Canvas dimensions (logical px, devicePixelRatio applied in draw)
const W = 380;
const H = 300;
const CB_W = 24; // colorbar strip width (px)
const CB_PAD = 40; // right gutter for colorbar + labels
const PLOT_W = W - CB_PAD; // mesh area
const GRID = 56; // max columns after downsample
const MARGIN = 12; // px padding inside mesh area

// ── colormap helpers ─────────────────────────────────────────────────────────

/** Sample the 256-entry LUT at a normalised t ∈ [0, 1]. Returns css rgb(). */
function lutSample(lut: Uint8Array, t: number): string {
  const i = Math.max(0, Math.min(255, Math.round(t * 255)));
  const r = lut[i * 4];
  const g = lut[i * 4 + 1];
  const b = lut[i * 4 + 2];
  return `rgb(${r},${g},${b})`;
}

// ── main component ────────────────────────────────────────────────────────────

export default function SurfaceView() {
  const raster = useStageInfo((s) => s.raster);

  // Stable selector: return the display object directly (never a fresh `??{}`)
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zScale, setZScale] = useState(0.6);
  const [az, setAz] = useState(DEFAULT_AZ);
  const [el, setEl] = useState(DEFAULT_EL);

  // Pointer drag state (ref so we never re-render on every move)
  const dragRef = useRef<{ lastX: number; lastY: number } | null>(null);

  // Build the LUT once per cmap change (memoised, stable reference)
  const lut = useMemo(() => buildLut(display.cmap), [display.cmap]);

  // ── downsample ──────────────────────────────────────────────────────────────
  const grid = useMemo(() => {
    if (!raster) return null;
    const step = Math.max(1, Math.ceil(raster.w / GRID));
    const gw = Math.floor(raster.w / step);
    const gh = Math.floor(raster.h / step);
    const z = new Float32Array(gw * gh);
    for (let gy = 0; gy < gh; gy++) {
      for (let gx = 0; gx < gw; gx++) {
        let sum = 0;
        for (let dy = 0; dy < step; dy++) {
          for (let dx = 0; dx < step; dx++) {
            sum +=
              raster.data[(gy * step + dy) * raster.w + gx * step + dx];
          }
        }
        z[gy * gw + gx] = sum / (step * step) / 65535; // normalised [0,1]
      }
    }
    return { gw, gh, z };
  }, [raster]);

  // ── draw ────────────────────────────────────────────────────────────────────
  const draw = useCallback(() => {
    const cv = canvasRef.current;
    if (!cv || !grid) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    const { gw, gh, z } = grid;
    const zh = zScale; // relative height exaggeration within the unit cube

    // Map grid coords to unit cube [0,1]³
    const unitZ = (gx: number, gy: number): number =>
      z[gy * gw + gx] * zh;

    // Project a grid point into screen space (within the PLOT_W × H area)
    const pt = (gx: number, gy: number): { sx: number; sy: number } =>
      project(
        gx / Math.max(gw - 1, 1),
        gy / Math.max(gh - 1, 1),
        unitZ(gx, gy),
        az,
        el,
        PLOT_W,
        H,
        MARGIN,
      );

    ctx.clearRect(0, 0, W, H);

    // ── draw filled quads back-to-front (painter's algorithm) ─────────────
    // Determine draw order: we want to iterate rows/columns so that nearer
    // faces overdraw farther ones. The heuristic: if az (mod 360) makes the
    // Y-axis face toward the viewer we iterate gy forward else backward; for
    // X similarly for gx. Good enough for a convex terrain.
    const azN = ((az % 360) + 360) % 360;
    const gyStart = azN < 180 ? gh - 2 : 0;
    const gyEnd = azN < 180 ? -1 : gh - 1;
    const gyStep = azN < 180 ? -1 : 1;
    const gxStart = (azN > 90 && azN < 270) ? 0 : gw - 2;
    const gxEnd = (azN > 90 && azN < 270) ? gw - 1 : -1;
    const gxStep = (azN > 90 && azN < 270) ? 1 : -1;

    for (let gy = gyStart; gy !== gyEnd; gy += gyStep) {
      for (let gx = gxStart; gx !== gxEnd; gx += gxStep) {
        // Average z of the quad's four corners for colouring
        const zAvg =
          (z[gy * gw + gx] +
            z[gy * gw + gx + 1] +
            z[(gy + 1) * gw + gx] +
            z[(gy + 1) * gw + gx + 1]) /
          4;

        const color = lutSample(lut, zAvg);
        const p00 = pt(gx, gy);
        const p10 = pt(gx + 1, gy);
        const p11 = pt(gx + 1, gy + 1);
        const p01 = pt(gx, gy + 1);

        ctx.beginPath();
        ctx.moveTo(p00.sx, p00.sy);
        ctx.lineTo(p10.sx, p10.sy);
        ctx.lineTo(p11.sx, p11.sy);
        ctx.lineTo(p01.sx, p01.sy);
        ctx.closePath();
        ctx.fillStyle = color;
        ctx.fill();
        // thin edge so adjacent quads don't bleed together
        ctx.strokeStyle = "rgba(0,0,0,0.15)";
        ctx.lineWidth = 0.3;
        ctx.stroke();
      }
    }

    // ── colorbar ────────────────────────────────────────────────────────────
    const cbX = PLOT_W + 8;
    const cbY = 10;
    const cbH = H - 20;

    // gradient from bottom (low) to top (high) using the LUT
    const grad = ctx.createLinearGradient(0, cbY + cbH, 0, cbY);
    const steps = 16;
    for (let i = 0; i <= steps; i++) {
      const t = i / steps;
      const ii = Math.round(t * 255);
      const r = lut[ii * 4];
      const g = lut[ii * 4 + 1];
      const b = lut[ii * 4 + 2];
      grad.addColorStop(t, `rgb(${r},${g},${b})`);
    }
    ctx.fillStyle = grad;
    ctx.fillRect(cbX, cbY, CB_W, cbH);
    ctx.strokeStyle = "rgba(128,128,128,0.5)";
    ctx.lineWidth = 0.5;
    ctx.strokeRect(cbX, cbY, CB_W, cbH);

    // tick labels: min at bottom, max at top, mid in centre
    const vmin = raster
      ? (raster.vmin ?? 0)
      : 0;
    const vmax = raster ? (raster.vmax ?? 1) : 1;
    const ticks = [
      { t: 0, label: fmtVal(vmin) },
      { t: 0.5, label: fmtVal((vmin + vmax) / 2) },
      { t: 1, label: fmtVal(vmax) },
    ];
    ctx.fillStyle = getComputedStyle(document.documentElement)
      .getPropertyValue("--text")
      .trim() || "#e5e5e5";
    ctx.font = "9px sans-serif";
    ctx.textAlign = "left";
    for (const { t, label } of ticks) {
      const y = cbY + cbH - t * cbH;
      ctx.fillText(label, cbX + CB_W + 3, y + 3);
    }

    // unit label rotated vertically
    const unit = meta?.pixel_unit ?? "";
    if (unit) {
      ctx.save();
      ctx.translate(cbX + CB_W + 30, cbY + cbH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "center";
      ctx.font = "8px sans-serif";
      ctx.fillText(unit, 0, 0);
      ctx.restore();
    }
  }, [grid, lut, az, el, zScale, raster, meta]);

  useEffect(() => {
    draw();
  }, [draw]);

  // ── pointer-drag orbit ───────────────────────────────────────────────────
  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { lastX: e.clientX, lastY: e.clientY };
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      if (!dragRef.current) return;
      const dx = e.clientX - dragRef.current.lastX;
      const dy = e.clientY - dragRef.current.lastY;
      dragRef.current = { lastX: e.clientX, lastY: e.clientY };
      const { dAz, dEl } = dragToOrbit(dx, dy);
      setAz((a) => normaliseAz(a + dAz));
      setEl((el_) => clampEl(el_ + dEl));
    },
    [],
  );

  const onPointerUp = useCallback(() => {
    dragRef.current = null;
  }, []);

  if (!meta || meta.kind === "spectrum" || !raster) {
    return <div className="fvd-ws-empty">Select a 2D image.</div>;
  }

  return (
    <div className="fvd-ws">
      <canvas
        ref={canvasRef}
        width={W}
        height={H}
        style={{ cursor: "grab", touchAction: "none" }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      />
      <div className="fvd-ws-row">
        <span className="k">relief</span>
        <input
          type="range"
          min={0.1}
          max={1.5}
          step={0.05}
          value={zScale}
          style={{ flex: 1 }}
          onChange={(e) => setZScale(Number(e.target.value))}
        />
        <button
          style={{ marginLeft: 6, fontSize: 10, padding: "1px 5px" }}
          onClick={() => { setAz(DEFAULT_AZ); setEl(DEFAULT_EL); }}
          title="Reset view to MATLAB default (az=45°, el=30°)"
        >
          reset
        </button>
      </div>
    </div>
  );
}

// ── helpers ───────────────────────────────────────────────────────────────────

/** Format a value for the colorbar tick label — 3 sig-figs, trim trailing zeros. */
function fmtVal(v: number): string {
  if (!Number.isFinite(v)) return "?";
  if (v === 0) return "0";
  const abs = Math.abs(v);
  if (abs >= 1000 || abs < 0.001) return v.toExponential(1);
  return parseFloat(v.toPrecision(3)).toString();
}
