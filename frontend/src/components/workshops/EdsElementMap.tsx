// EDS element-map canvas (hot colormap). Extracted from EdsSpectrumImage.tsx
// to keep the explorer under the module-size ceiling as the element-navigation
// features grow.

import { useEffect, useMemo, useRef } from "react";

import type { EdsElementMapResult } from "../../lib/api";

export default function MapCanvas({
  result,
}: {
  result: EdsElementMapResult;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [h, w] = result.shape;
  // iterative max — Math.max(...flat) spreads every element as a call
  // argument and throws a RangeError once the map crosses ~65k px
  const vmax = useMemo(() => {
    let m = 1;
    for (const row of result.map) {
      for (const v of row) {
        if (v > m) m = v;
      }
    }
    return m;
  }, [result.map]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv) return;
    cv.width = w;
    cv.height = h;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const img = ctx.createImageData(w, h);
    for (let i = 0; i < h * w; i++) {
      const row = Math.floor(i / w);
      const col = i % w;
      const v = Math.min(255, Math.round((result.map[row][col] / vmax) * 255));
      // hot colormap approximation: black→red→yellow→white
      const r = Math.min(255, v * 3);
      const g = Math.max(0, Math.min(255, v * 3 - 255));
      const b = Math.max(0, Math.min(255, v * 3 - 510));
      img.data[i * 4] = r;
      img.data[i * 4 + 1] = g;
      img.data[i * 4 + 2] = b;
      img.data[i * 4 + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
  }, [result, h, w, vmax]);

  return (
    <canvas
      ref={canvasRef}
      title={`${result.e_lo.toFixed(3)}–${result.e_hi.toFixed(3)} keV (${result.bg} bg)`}
      style={{ width: "100%", imageRendering: "pixelated", display: "block" }}
    />
  );
}
