// EDS composite mode (prototype "EDS Composite" — the #1 ranked design
// gap): per-element channel list with colour / intensity / visibility,
// additively blended on a canvas from the at% maps' raw data16 rasters.

import { useEffect, useRef, useState } from "react";

import { fetchData16, type Raster16 } from "../../lib/api";

export interface Channel {
  id: string; // derived at%-map image id
  el: string;
  color: string;
  intensity: number; // 0–2
  visible: boolean;
}

/** Classic EDS overlay palette, assigned in element order. */
export const EDS_PALETTE = [
  "#f43f5e", // red
  "#22c55e", // green
  "#3b82f6", // blue
  "#eab308", // yellow
  "#a855f7", // purple
  "#06b6d4", // cyan
  "#f97316", // orange
  "#ec4899", // pink
];

const VIEW_W = 300;

function hexToRgb(hex: string): [number, number, number] {
  const c = hex.replace("#", "");
  return [
    parseInt(c.slice(0, 2), 16) || 0,
    parseInt(c.slice(2, 4), 16) || 0,
    parseInt(c.slice(4, 6), 16) || 0,
  ];
}

export default function EdsComposite({
  channels,
  onChange,
}: {
  channels: Channel[];
  onChange: (chs: Channel[]) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const cacheRef = useRef(new Map<string, Raster16>());
  const [dims, setDims] = useState<{ w: number; h: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (channels.length === 0) return;
    let stale = false;
    (async () => {
      try {
        const rasters = await Promise.all(
          channels.map(async (c) => {
            let r = cacheRef.current.get(c.id);
            if (!r) {
              r = await fetchData16(c.id);
              cacheRef.current.set(c.id, r);
            }
            return r;
          }),
        );
        if (stale) return;
        const { w, h } = rasters[0];
        const acc = new Float32Array(w * h * 3);
        channels.forEach((c, k) => {
          if (!c.visible) return;
          const { data } = rasters[k];
          const [r, g, b] = hexToRgb(c.color);
          const gain = c.intensity / 65535;
          for (let i = 0; i < w * h; i++) {
            const v = data[i] * gain;
            acc[i * 3] += v * r;
            acc[i * 3 + 1] += v * g;
            acc[i * 3 + 2] += v * b;
          }
        });
        const img = new ImageData(w, h);
        for (let i = 0; i < w * h; i++) {
          img.data[i * 4] = Math.min(255, acc[i * 3]);
          img.data[i * 4 + 1] = Math.min(255, acc[i * 3 + 1]);
          img.data[i * 4 + 2] = Math.min(255, acc[i * 3 + 2]);
          img.data[i * 4 + 3] = 255;
        }
        const cv = canvasRef.current;
        if (!cv) return;
        cv.width = w;
        cv.height = h;
        cv.getContext("2d")!.putImageData(img, 0, 0);
        setDims({ w, h });
        setErr(null);
      } catch (e) {
        if (!stale) setErr((e as Error).message);
      }
    })();
    return () => {
      stale = true;
    };
  }, [channels]);

  if (channels.length === 0) return null;

  const set = (i: number, patch: Partial<Channel>) =>
    onChange(channels.map((c, k) => (k === i ? { ...c, ...patch } : c)));

  const savePng = () => {
    canvasRef.current?.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `composite_${channels
        .filter((c) => c.visible)
        .map((c) => c.el)
        .join("")}.png`;
      a.click();
      URL.revokeObjectURL(url);
    });
  };

  const viewH = dims ? (dims.h / dims.w) * VIEW_W : VIEW_W;

  return (
    <>
      <div className="fvd-ws-row">
        <span className="k">Composite</span>
        <button className="fvd-btn" onClick={savePng} disabled={!dims}>
          Save PNG
        </button>
      </div>
      <div
        className="fvd-ws-pattern"
        style={{ width: VIEW_W, height: viewH }}
      >
        <canvas
          ref={canvasRef}
          style={{
            width: VIEW_W,
            height: viewH,
            imageRendering: "pixelated",
          }}
        />
      </div>
      {err && <div className="fvd-ws-note">composite: {err}</div>}
      {channels.map((c, i) => (
        <div className="fvd-ws-row" key={c.id}>
          <input
            type="checkbox"
            checked={c.visible}
            title="visible"
            onChange={(e) => set(i, { visible: e.target.checked })}
          />
          <input
            type="color"
            value={c.color}
            title="channel colour"
            style={{ width: 28, height: 20, padding: 0, border: "none" }}
            onChange={(e) => set(i, { color: e.target.value })}
          />
          <span className="k" style={{ width: 24 }}>
            {c.el}
          </span>
          <input
            type="range"
            min={0}
            max={2}
            step={0.05}
            value={c.intensity}
            style={{ flex: 1 }}
            onChange={(e) => set(i, { intensity: Number(e.target.value) })}
          />
          <span className="k" style={{ width: 32, textAlign: "right" }}>
            {c.intensity.toFixed(2)}
          </span>
        </div>
      ))}
    </>
  );
}
