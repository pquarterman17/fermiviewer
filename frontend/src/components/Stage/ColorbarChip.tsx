// Calibrated colorbar (checklist I): vertical LUT gradient on the
// stage's right edge with the display window's real-value endpoints.

import { useEffect, useRef } from "react";

import { buildLut } from "../../lib/colormaps";
import { useStageInfo } from "../../store/stage";
import { useViewer, DEFAULT_DISPLAY } from "../../store/viewer";

const W = 14;
const H = 160;

function fmt(v: number): string {
  const a = Math.abs(v);
  if (a !== 0 && (a < 0.01 || a >= 1e5)) return v.toExponential(1);
  return Number(v.toPrecision(4)).toString();
}

export default function ColorbarChip() {
  const show = useViewer((s) => s.colorbar);
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
    // buildLut returns a flat RGBA Uint8Array (256 × 4)
    const lut = buildLut(display.cmap as Parameters<typeof buildLut>[0]);
    const img = ctx.createImageData(W, H);
    for (let y = 0; y < H; y++) {
      const o4 = Math.round(((H - 1 - y) / (H - 1)) * 255) * 4;
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

  return (
    <div className="fvd-glass fvd-colorbar">
      {unit && <span className="u">{unit}</span>}
      <span className="v">{fmt(hi)}</span>
      <canvas ref={canvasRef} width={W} height={H} />
      <span className="v">{fmt(lo)}</span>
    </div>
  );
}
