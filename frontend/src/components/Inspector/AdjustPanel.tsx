// Adjust card (handoff §4 Inspector · Image): histogram with draggable
// black/white window handles, gamma slider, colormap picker, auto/reset.

import { useEffect, useMemo, useRef, useState } from "react";

import { fetchHistogram, type Histogram } from "../../lib/api";
import { COLORMAP_NAMES, type ColormapName } from "../../lib/colormaps";
import { autoWindow, toNorm, toReal } from "../../lib/display";
import { loadPrefs } from "../../lib/prefs";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY, useViewer } from "../../store/viewer";
import Card from "./Card";

const HIST_H = 80;

/** Number input that only resyncs from props when not being edited, so
 *  typing isn't clobbered by the live store value it commits to. */
function NumField(props: {
  value: number | null;
  onCommit: (v: number) => void;
  step?: number;
  title?: string;
}) {
  const { value, onCommit, step, title } = props;
  const [text, setText] = useState("");
  const focused = useRef(false);
  useEffect(() => {
    if (!focused.current) setText(value == null ? "" : String(value));
  }, [value]);
  return (
    <input
      type="number"
      className="fvd-numfield"
      title={title}
      step={step}
      value={text}
      onFocus={() => (focused.current = true)}
      onBlur={() => {
        focused.current = false;
        setText(value == null ? "" : String(value));
      }}
      onChange={(e) => {
        setText(e.target.value);
        const v = Number(e.target.value);
        if (e.target.value !== "" && Number.isFinite(v)) onCommit(v);
      }}
    />
  );
}

export default function AdjustPanel() {
  const activeId = useViewer((s) => s.activeId);
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  const setDisplay = useViewer((s) => s.setDisplay);
  const unit = useViewer((s) =>
    s.activeId ? (s.images[s.activeId]?.value_unit ?? "") : "",
  );
  const colorbar = useViewer((s) => s.colorbar);
  const toggleColorbar = useViewer((s) => s.toggleColorbar);
  const colorbarSide = useViewer((s) => s.colorbarSide);
  const setColorbarSide = useViewer((s) => s.setColorbarSide);
  const raster = useStageInfo((s) => s.raster);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hist, setHist] = useState<Histogram | null>(null);
  const [logScale, setLogScale] = useState(false);
  const dragRef = useRef<"lo" | "hi" | null>(null);

  // cumulative u16 histogram → clip fractions for the current window
  const cumHist = useMemo(() => {
    if (!raster) return null;
    const counts = new Float64Array(65536);
    for (let i = 0; i < raster.data.length; i++) counts[raster.data[i]]++;
    for (let i = 1; i < 65536; i++) counts[i] += counts[i - 1];
    return counts;
  }, [raster]);

  const clipPct = (norm: number, above: boolean): number => {
    if (!cumHist || !raster) return 0;
    const n = raster.data.length;
    const idx = Math.min(65535, Math.max(0, Math.floor(norm * 65535)));
    const below = cumHist[idx] / n;
    return 100 * (above ? 1 - below : below);
  };

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
      // sqrt by default; log-scale toggle for sparse spectra
      const frac = logScale
        ? Math.log1p(hist.counts[i]) / Math.log1p(max)
        : Math.sqrt(hist.counts[i] / max);
      const bh = frac * (h - 4);
      ctx.fillRect((i / n) * w, h - bh, Math.max(1, w / n - 0.5), bh);
    }
    // window handles + shaded out-of-window regions
    const xLo = display.lo * w;
    const xHi = display.hi * w;
    ctx.fillStyle = "rgba(0,0,0,0.35)";
    ctx.fillRect(0, 0, xLo, h);
    ctx.fillRect(xHi, 0, w - xHi, h);
    // thick rounded handle bars (prototype style)
    ctx.fillStyle = accent;
    const hw = 6; // handle width
    const hh = Math.round(h * 0.55);
    for (const x of [xLo, xHi]) {
      const hx = Math.min(Math.max(x - hw / 2, 0), w - hw);
      ctx.beginPath();
      ctx.roundRect(hx, (h - hh) / 2, hw, hh, 3);
      ctx.fill();
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
  }, [hist, display.lo, display.hi, logScale]);

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
    <Card title="Adjust" defaultOpen={false}>
      <div className="fvd-adjust-top">
        <button
          className="fvd-btn"
          title="Percentile auto-contrast  A"
          onClick={() => {
            if (!raster) return;
            const p = loadPrefs();
            setDisplay(activeId, autoWindow(raster, p.autoLoPct, p.autoHiPct));
          }}
        >
          ◑ Auto
        </button>
        <button
          className="fvd-btn"
          onClick={() =>
            setDisplay(activeId, { lo: 0, hi: 1, gamma: 1, invert: false })
          }
          title="Reset contrast window, gamma and invert to defaults"
        >
          Reset
        </button>
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
      <canvas
        ref={canvasRef}
        className="fvd-hist"
        style={{ height: HIST_H }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
      />
      <div className="fvd-bw-row">
        <span className="k">Black</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.002}
          value={display.lo}
          onChange={(e) =>
            setDisplay(activeId, {
              lo: Math.min(Number(e.target.value), display.hi - 1 / 255),
            })
          }
        />
        <span className="v">{fmtReal(display.lo)}</span>
      </div>
      <div className="fvd-bw-row">
        <span className="k">White</span>
        <input
          type="range"
          min={0}
          max={1}
          step={0.002}
          value={display.hi}
          onChange={(e) =>
            setDisplay(activeId, {
              hi: Math.max(Number(e.target.value), display.lo + 1 / 255),
            })
          }
        />
        <span className="v">{fmtReal(display.hi)}</span>
      </div>
      <div className="fvd-meta-row">
        <span className="k">
          Clip{" "}
          <button
            className={`fvd-seg-btn fvd-inline-toggle${logScale ? " active" : ""}`}
            title="Log-scale histogram"
            onClick={() => setLogScale(!logScale)}
          >
            log
          </button>
        </span>
        <span className="v">
          ◢ {clipPct(display.lo, false).toFixed(1)}% · ◤{" "}
          {clipPct(display.hi, true).toFixed(1)}%
        </span>
      </div>
      <div className="fvd-chip-row">
        <span className="fvd-chip" title="Gamma — scroll or drag">
          γ{" "}
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
          />{" "}
          {display.gamma.toFixed(2)}
        </span>
        <button
          className={`fvd-chip${display.invert ? " active" : ""}`}
          onClick={() => setDisplay(activeId, { invert: !display.invert })}
          title="Invert the display (swap black/white)"
        >
          invert {display.invert ? "on" : "off"}
        </button>
        <button
          className={`fvd-chip${display.transform !== "linear" ? " active" : ""}`}
          title="Intensity transform: linear → log → equalize"
          onClick={() =>
            setDisplay(activeId, {
              transform:
                display.transform === "linear"
                  ? "log"
                  : display.transform === "log"
                    ? "equalize"
                    : "linear",
            })
          }
        >
          {display.transform}
        </button>
      </div>

      {raster && (
        <div className="fvd-zscale">
          <div className="fvd-meta-row">
            <span className="k">Color range{unit ? ` (${unit})` : ""}</span>
            <button
              className={`fvd-seg-btn fvd-inline-toggle${colorbar ? " active" : ""}`}
              title="Show the color scale bar on the stage"
              onClick={toggleColorbar}
            >
              scale bar
            </button>
          </div>
          <div className="fvd-zscale-row">
            <NumField
              title="Minimum (black point)"
              value={Number(toReal(display.lo, raster).toPrecision(6))}
              onCommit={(v) =>
                setDisplay(activeId, {
                  lo: Math.min(toNorm(v, raster), display.hi - 1 / 255),
                })
              }
            />
            <span className="dash">–</span>
            <NumField
              title="Maximum (white point)"
              value={Number(toReal(display.hi, raster).toPrecision(6))}
              onCommit={(v) =>
                setDisplay(activeId, {
                  hi: Math.max(toNorm(v, raster), display.lo + 1 / 255),
                })
              }
            />
            <span className="unit">{unit}</span>
          </div>
          <div className="fvd-zscale-row">
            <span className="k">Tick step</span>
            <NumField
              title="Colorbar tick interval (0 = auto)"
              value={
                display.tickStep && display.tickStep > 0
                  ? display.tickStep
                  : null
              }
              onCommit={(v) =>
                setDisplay(activeId, { tickStep: Math.max(0, v) })
              }
            />
            <span className="unit">{unit}</span>
            <div className="fvd-seg" title="Colorbar side (L / R / bottom)">
              <button
                className={`fvd-seg-btn${colorbarSide === "left" ? " active" : ""}`}
                onClick={() => setColorbarSide("left")}
              >
                L
              </button>
              <button
                className={`fvd-seg-btn${colorbarSide === "right" ? " active" : ""}`}
                onClick={() => setColorbarSide("right")}
              >
                R
              </button>
              <button
                className={`fvd-seg-btn${colorbarSide === "bottom" ? " active" : ""}`}
                onClick={() => setColorbarSide("bottom")}
              >
                B
              </button>
            </div>
          </div>
          {/* Tick count (audit #9): count-based mode — overrides tick step */}
          <div className="fvd-zscale-row">
            <span className="k">Tick count</span>
            <NumField
              title="Number of colorbar ticks (overrides step when > 0; 0 = use step)"
              value={
                display.tickCount && display.tickCount > 0
                  ? display.tickCount
                  : null
              }
              onCommit={(v) =>
                setDisplay(activeId, { tickCount: Math.max(0, Math.round(v)) })
              }
            />
            <button
              className="fvd-icon-btn"
              title="Clear tick count (revert to step mode)"
              onClick={() => setDisplay(activeId, { tickCount: 0 })}
            >
              ↺
            </button>
          </div>
          {/* Tick font size (audit #9) */}
          <div className="fvd-zscale-row">
            <span className="k">Tick font</span>
            <NumField
              title="Colorbar tick-label font size (px; default 11)"
              value={
                display.tickFontSize && display.tickFontSize > 0
                  ? display.tickFontSize
                  : null
              }
              onCommit={(v) =>
                setDisplay(activeId, {
                  tickFontSize: Math.min(48, Math.max(6, Math.round(v))),
                })
              }
            />
            <span className="unit">px</span>
            {display.tickFontSize && (
              <button
                className="fvd-icon-btn"
                title="Reset to default"
                onClick={() =>
                  setDisplay(activeId, { tickFontSize: undefined })
                }
              >
                ↺
              </button>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}
