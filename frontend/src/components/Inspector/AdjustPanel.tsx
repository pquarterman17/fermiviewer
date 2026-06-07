// Adjust card (handoff §4 Inspector · Image): histogram with draggable
// black/white window handles, gamma slider, colormap picker, auto/reset.

import { useEffect, useRef, useState } from "react";

import { fetchHistogram, type Histogram } from "../../lib/api";
import { COLORMAP_NAMES, type ColormapName } from "../../lib/colormaps";
import { autoWindow, toReal } from "../../lib/display";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY, useViewer } from "../../store/viewer";

const HIST_H = 80;

export default function AdjustPanel() {
  const activeId = useViewer((s) => s.activeId);
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const setDisplay = useViewer((s) => s.setDisplay);
  const raster = useStageInfo((s) => s.raster);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hist, setHist] = useState<Histogram | null>(null);
  const dragRef = useRef<"lo" | "hi" | null>(null);

  useEffect(() => {
    setHist(null);
    if (!activeId) return;
    let alive = true;
    fetchHistogram(activeId, 128)
      .then((h) => {
        if (alive) setHist(h);
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, [activeId]);

  // ── histogram + window handles painting ──
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !hist) return;
    const dpr = window.devicePixelRatio || 1;
    const w = canvas.clientWidth;
    const h = HIST_H;
    canvas.width = w * dpr;
    canvas.height = h * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.scale(dpr, dpr);
    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    const faint = styles.getPropertyValue("--text-faint").trim() || "#888";

    ctx.clearRect(0, 0, w, h);
    const max = Math.max(...hist.counts, 1);
    const n = hist.counts.length;
    ctx.fillStyle = faint;
    for (let i = 0; i < n; i++) {
      // sqrt scaling keeps sparse high-count bins from flattening the rest
      const bh = Math.sqrt(hist.counts[i] / max) * (h - 4);
      ctx.fillRect((i / n) * w, h - bh, Math.max(1, w / n - 0.5), bh);
    }
    // window handles + shaded out-of-window regions
    const xLo = display.lo * w;
    const xHi = display.hi * w;
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(0, 0, xLo, h);
    ctx.fillRect(xHi, 0, w - xHi, h);
    ctx.strokeStyle = accent;
    ctx.lineWidth = 2;
    for (const x of [xLo, xHi]) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }
    // transfer ramp lo→hi
    ctx.strokeStyle = accent;
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(xLo, h);
    ctx.lineTo(xHi, 0);
    ctx.stroke();
    ctx.setLineDash([]);
  }, [hist, display.lo, display.hi]);

  // ── handle dragging ──
  const normAt = (e: React.PointerEvent): number => {
    const r = canvasRef.current!.getBoundingClientRect();
    return Math.min(1, Math.max(0, (e.clientX - r.left) / r.width));
  };

  const onDown = (e: React.PointerEvent) => {
    if (!activeId) return;
    const t = normAt(e);
    dragRef.current =
      Math.abs(t - display.lo) <= Math.abs(t - display.hi) ? "lo" : "hi";
    (e.target as Element).setPointerCapture(e.pointerId);
    onMove(e);
  };

  const onMove = (e: React.PointerEvent) => {
    if (!dragRef.current || !activeId) return;
    const t = normAt(e);
    if (dragRef.current === "lo") {
      setDisplay(activeId, { lo: Math.min(t, display.hi - 1 / 255) });
    } else {
      setDisplay(activeId, { hi: Math.max(t, display.lo + 1 / 255) });
    }
  };

  const onUp = () => {
    dragRef.current = null;
  };

  if (!activeId) return null;

  const fmtReal = (norm: number) =>
    raster ? Number(toReal(norm, raster).toPrecision(5)).toString() : "—";

  return (
    <div className="fvd-card">
      <h3>Adjust</h3>
      <canvas
        ref={canvasRef}
        className="fvd-hist"
        style={{ height: HIST_H }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      />
      <div className="fvd-meta-row">
        <span className="k">Window</span>
        <span className="v">
          {fmtReal(display.lo)} – {fmtReal(display.hi)}
        </span>
      </div>
      <div className="fvd-slider-row">
        <span className="k">γ</span>
        <input
          type="range"
          min={-1}
          max={1}
          step={0.01}
          value={Math.log10(display.gamma)}
          onChange={(e) =>
            setDisplay(activeId, {
              gamma: Math.pow(10, Number(e.target.value)),
            })
          }
        />
        <span className="v">{display.gamma.toFixed(2)}</span>
      </div>
      <div className="fvd-slider-row">
        <span className="k">Map</span>
        <select
          value={display.cmap}
          onChange={(e) =>
            setDisplay(activeId, { cmap: e.target.value as ColormapName })
          }
        >
          {COLORMAP_NAMES.map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
      <div className="fvd-slider-row">
        <span className="k">Invert</span>
        <label className="fvd-check">
          <input
            type="checkbox"
            checked={display.invert}
            onChange={(e) =>
              setDisplay(activeId, { invert: e.target.checked })
            }
          />
        </label>
      </div>
      <div className="fvd-btn-row">
        <button
          className="fvd-btn"
          title="Percentile auto-contrast  A"
          onClick={() => raster && setDisplay(activeId, autoWindow(raster))}
        >
          Auto
        </button>
        <button
          className="fvd-btn"
          onClick={() =>
            setDisplay(activeId, { lo: 0, hi: 1, gamma: 1, invert: false })
          }
        >
          Reset
        </button>
      </div>
    </div>
  );
}
