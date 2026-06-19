// Calibrated colorbar (checklist I): a full-height vertical LUT gradient
// pinned to the left, right, or bottom stage edge (audit #9), with labeled
// tick marks in real value units (nm for AFM height).
//
// Tick mode: if tickCount > 0 it drives the interval (count-based, audit #9);
// otherwise tickStep is used (step-based, original behaviour).
// Tick-label font size is user-configurable (audit #9, tickFontSize in Display).

import { useEffect, useRef } from "react";

import { buildLut } from "../../lib/colormaps";
import { colorbarTicks, niceStep } from "../../lib/display";
import { useStageInfo } from "../../store/stage";
import { DEFAULT_DISPLAY, useViewer } from "../../store/viewer";

const W = 14; // gradient internal width (px); CSS stretches height to full
const LUT_H = 256;
const DEFAULT_TICK_FONT = 11; // px — matches the original SVG export font-size

function fmt(v: number): string {
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(1);
  return Number(v.toPrecision(4)).toString();
}

export default function ColorbarChip() {
  const show = useViewer((s) => s.colorbar);
  const side = useViewer((s) => s.colorbarSide);
  const display = useViewer((s) =>
    s.activeId ? (s.display[s.activeId] ?? DEFAULT_DISPLAY) : DEFAULT_DISPLAY,
  );
  // value unit (e.g. AFM height "nm") — labels the z lengthscale
  const unit = useViewer((s) =>
    s.activeId ? (s.images[s.activeId]?.value_unit ?? "") : "",
  );
  const raster = useStageInfo((s) => s.raster);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !show) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const lut = buildLut(display.cmap as Parameters<typeof buildLut>[0]);
    const img = ctx.createImageData(W, LUT_H);
    for (let y = 0; y < LUT_H; y++) {
      // y=0 is the top → highest value → LUT max
      const o4 = Math.round(((LUT_H - 1 - y) / (LUT_H - 1)) * 255) * 4;
      for (let x = 0; x < W; x++) {
        const o = (y * W + x) * 4;
        img.data[o] = lut[o4];
        img.data[o + 1] = lut[o4 + 1];
        img.data[o + 2] = lut[o4 + 2];
        img.data[o + 3] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }, [show, display.cmap]);

  if (!show || !raster) return null;
  const span = raster.vmax - raster.vmin || 1;
  const lo = raster.vmin + display.lo * span;
  const hi = raster.vmin + display.hi * span;

  // tick step: count-based (audit #9) takes priority over step-based
  const tickCount = display.tickCount;
  const tickFontSize = display.tickFontSize ?? DEFAULT_TICK_FONT;

  let step: number;
  if (tickCount && tickCount > 0) {
    // derive step from requested count so ticks land on round numbers
    step = niceStep(hi - lo, tickCount);
  } else {
    step =
      display.tickStep && display.tickStep > 0
        ? display.tickStep
        : niceStep(hi - lo);
  }
  let ticks = colorbarTicks(lo, hi, step);
  if (ticks.length === 0) {
    step = niceStep(hi - lo);
    ticks = colorbarTicks(lo, hi, step);
  }

  // bottom placement: horizontal gradient strip at the bottom of the viewport
  if (side === "bottom") {
    const posPct = (v: number) => ((v - lo) / (hi - lo)) * 100; // left=lo, right=hi
    return (
      <div className="fvd-colorbar side-bottom">
        {unit && <span className="u">{unit}</span>}
        <div className="body body-h">
          <canvas className="bar bar-h" ref={canvasRef} width={LUT_H} height={W} />
          <div className="ticks ticks-h">
            {ticks.map((v) => (
              <span
                className="tk tk-h"
                key={v}
                style={{ left: `${posPct(v)}%`, fontSize: tickFontSize }}
              >
                <i className="ln ln-v" />
                <em className="n">{fmt(v)}</em>
              </span>
            ))}
          </div>
        </div>
      </div>
    );
  }

  const posPct = (v: number) => ((hi - v) / (hi - lo)) * 100;

  return (
    <div className={`fvd-colorbar side-${side}`}>
      {unit && <span className="u">{unit}</span>}
      <div className="body">
        <canvas className="bar" ref={canvasRef} width={W} height={LUT_H} />
        <div className="ticks">
          {ticks.map((v) => (
            <span className="tk" key={v} style={{ top: `${posPct(v)}%`, fontSize: tickFontSize }}>
              <i className="ln" />
              <em className="n">{fmt(v)}</em>
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
