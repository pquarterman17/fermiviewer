// Surface plot (checklist K): isometric wireframe of the active
// raster — downsampled to ≤64 columns, drawn on a canvas. Height maps
// the display window so the Adjust panel drives the relief.

import { useEffect, useRef, useState } from "react";

import { useStageInfo } from "../../store/stage";
import { useViewer } from "../../store/viewer";

const W = 320;
const H = 260;
const GRID = 56; // max columns after downsample

export default function SurfaceView() {
  const raster = useStageInfo((s) => s.raster);
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [zScale, setZScale] = useState(0.6);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !raster) return;
    const ctx = cv.getContext("2d");
    if (!ctx) return;

    // block-mean downsample to ≤GRID columns (keep aspect)
    const step = Math.max(1, Math.ceil(raster.w / GRID));
    const gw = Math.floor(raster.w / step);
    const gh = Math.floor(raster.h / step);
    const z = new Float32Array(gw * gh);
    for (let gy = 0; gy < gh; gy++) {
      for (let gx = 0; gx < gw; gx++) {
        let sum = 0;
        for (let dy = 0; dy < step; dy++) {
          for (let dx = 0; dx < step; dx++) {
            sum += raster.data[(gy * step + dy) * raster.w + gx * step + dx];
          }
        }
        z[gy * gw + gx] = sum / (step * step) / 65535;
      }
    }

    // isometric projection: x' = (gx - gy)·cos30, y' = (gx + gy)·sin30 − z·h
    const c30 = Math.cos(Math.PI / 6);
    const s30 = Math.sin(Math.PI / 6);
    const cell = Math.min(
      W / ((gw + gh) * c30),
      (H * 0.55) / ((gw + gh) * s30),
    );
    const zh = H * 0.4 * zScale;
    const ox = W / 2;
    const oy = H - (gh * cell * s30) - 14;
    const px = (gx: number, gy: number): [number, number] => [
      ox + (gx - gy) * cell * c30,
      oy + (gx + gy) * cell * s30 - z[gy * gw + gx] * zh,
    ];

    const styles = getComputedStyle(document.documentElement);
    const accent = styles.getPropertyValue("--accent").trim() || "#a78bfa";
    ctx.clearRect(0, 0, W, H);
    ctx.lineWidth = 0.7;
    // back-to-front rows so nearer lines overdraw farther ones
    for (let gy = 0; gy < gh; gy++) {
      const t = gy / Math.max(gh - 1, 1);
      ctx.strokeStyle = `color-mix(in srgb, ${accent} ${30 + 60 * t}%, transparent)`;
      ctx.beginPath();
      for (let gx = 0; gx < gw; gx++) {
        const [x, y] = px(gx, gy);
        if (gx === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
    for (let gx = 0; gx < gw; gx += 2) {
      ctx.strokeStyle = `color-mix(in srgb, ${accent} 25%, transparent)`;
      ctx.beginPath();
      for (let gy = 0; gy < gh; gy++) {
        const [x, y] = px(gx, gy);
        if (gy === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
      }
      ctx.stroke();
    }
  }, [raster, zScale]);

  if (!meta || meta.kind === "spectrum" || !raster) {
    return <div className="fvd-ws-empty">Select a 2D image.</div>;
  }

  return (
    <div className="fvd-ws">
      <canvas ref={canvasRef} width={W} height={H} />
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
      </div>
    </div>
  );
}
