import { useEffect, useMemo, useRef, useState } from "react";

import type { EdsElementMapResult } from "../../lib/api";
import { buildLut, type ColormapName } from "../../lib/colormaps";
import {
  formatMapValue,
  mapDisplayRange,
  renderElementMap,
} from "../../lib/edsMapDisplay";

const MAP_COLORMAPS: ColormapName[] = [
  "viridis",
  "inferno",
  "fire",
  "ice",
  "gray",
];

function MapColorbar({
  cmap,
  lo,
  hi,
  background,
}: {
  cmap: ColormapName;
  lo: number;
  hi: number;
  background: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (!ctx) return;
    const lut = buildLut(cmap);
    const image = ctx.createImageData(256, 1);
    image.data.set(lut);
    ctx.putImageData(image, 0, 0);
  }, [cmap]);
  return (
    <div className="fvd-eds-map-colorbar">
      <canvas ref={ref} width={256} height={1} aria-hidden="true" />
      <div>
        <span>{formatMapValue(lo)}</span>
        <span>
          {background === "none"
            ? "integrated counts"
            : "background-subtracted counts"}
        </span>
        <span>{formatMapValue(hi)}</span>
      </div>
    </div>
  );
}

export default function EdsElementMap({
  result,
  busy,
  libraryBusy,
  compositeBusy,
  canAddToComposite,
  onAddToLibrary,
  onAddToComposite,
}: {
  result: EdsElementMapResult;
  busy: boolean;
  libraryBusy: boolean;
  compositeBusy: boolean;
  canAddToComposite: boolean;
  onAddToLibrary: (cmap: ColormapName) => void;
  onAddToComposite?: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [cmap, setCmap] = useState<ColormapName>("viridis");
  const [lowPct, setLowPct] = useState(1);
  const [highPct, setHighPct] = useState(99);
  const [h, w] = result.shape;
  const range = useMemo(
    () => mapDisplayRange(result.map, lowPct, highPct),
    [result.map, lowPct, highPct],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    canvas.width = w;
    canvas.height = h;
    const image = ctx.createImageData(w, h);
    image.data.set(renderElementMap(result.map, w, h, range, cmap));
    ctx.putImageData(image, 0, 0);
  }, [cmap, h, range, result.map, w]);

  const setContrast = (value: string) => {
    const [low, high] = value.split("-").map(Number);
    setLowPct(low);
    setHighPct(high);
  };

  return (
    <section className="fvd-eds-map-panel" aria-label="Element map">
      <header className="fvd-eds-map-header">
        <div>
          <strong>Element map</strong>
          <span className="fvd-eds-map-detail">
            {result.e_lo.toFixed(3)}–{result.e_hi.toFixed(3)} keV · {result.bg}{" "}
            background
          </span>
        </div>
        <span className="fvd-eds-source-chip" aria-live="polite">
          {busy
            ? "Updating…"
            : `${result.total_counts.toFixed(0)} total counts`}
        </span>
      </header>

      <div className="fvd-eds-map-toolbar">
        <label>
          <span>Colormap</span>
          <select
            value={cmap}
            onChange={(event) => setCmap(event.target.value as ColormapName)}
          >
            {MAP_COLORMAPS.map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
        </label>
        <label>
          <span>Contrast</span>
          <select
            value={`${lowPct}-${highPct}`}
            onChange={(event) => setContrast(event.target.value)}
          >
            <option value="1-99">Robust (1–99%)</option>
            <option value="0-100">Full range</option>
            <option value="5-99">High contrast (5–99%)</option>
          </select>
        </label>
        <div className="fvd-eds-map-actions">
          <button
            className="fvd-btn primary"
            disabled={libraryBusy}
            onClick={() => onAddToLibrary(cmap)}
          >
            {libraryBusy ? "Adding…" : "Add to library"}
          </button>
          {onAddToComposite && (
            <button
              className="fvd-btn"
              disabled={compositeBusy || !canAddToComposite}
              onClick={onAddToComposite}
            >
              {compositeBusy ? "Adding…" : "+ Composite"}
            </button>
          )}
        </div>
      </div>

      <div className="fvd-eds-map-canvas-wrap">
        <canvas
          ref={canvasRef}
          title={`${result.e_lo.toFixed(3)}–${result.e_hi.toFixed(3)} keV (${result.bg} background)`}
        />
      </div>
      <MapColorbar
        cmap={cmap}
        lo={range.lo}
        hi={range.hi}
        background={result.bg}
      />
      <footer className="fvd-eds-map-range">
        Data range {formatMapValue(range.dataMin)}–
        {formatMapValue(range.dataMax)}
        {result.bg !== "none" &&
          " · negative pixels are retained and clipped only for display"}
      </footer>
    </section>
  );
}
