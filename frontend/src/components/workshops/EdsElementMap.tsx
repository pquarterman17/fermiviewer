import { useEffect, useMemo, useRef, useState } from "react";

import type { EdsElementMapResult } from "../../lib/api";
import { buildLut, type ColormapName } from "../../lib/colormaps";
import { buildElementLut, useElementColors } from "../../lib/elemental/elementColors";
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

/** "element" is a generated black→element-colour→white ramp rather than one of
 *  the shared named colormaps, so a single-element map reads as the same colour
 *  that element wears in the composite and on its spectrum markers. */
export type MapPaint = ColormapName | "element";

function MapColorbar({
  lut,
  lo,
  hi,
  background,
}: {
  lut: Uint8Array;
  lo: number;
  hi: number;
  background: string;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const ctx = ref.current?.getContext("2d");
    if (!ctx) return;
    const image = ctx.createImageData(256, 1);
    image.data.set(lut);
    ctx.putImageData(image, 0, 0);
  }, [lut]);
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
  element,
  busy,
  libraryBusy,
  onAddToLibrary,
}: {
  result: EdsElementMapResult;
  /** "(custom)" or the selected element symbol — enables the element tint. */
  element: string;
  busy: boolean;
  libraryBusy: boolean;
  onAddToLibrary: (paint: MapPaint) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const colors = useElementColors();
  const [cmap, setCmap] = useState<MapPaint>("element");
  const [lowPct, setLowPct] = useState(1);
  const [highPct, setHighPct] = useState(99);
  const [h, w] = result.shape;
  const named = element !== "(custom)";
  // A window with no element behind it has no tint to use; fall back rather
  // than leaving the select on an option that cannot render.
  const paint: MapPaint = cmap === "element" && !named ? "viridis" : cmap;
  const range = useMemo(
    () => mapDisplayRange(result.map, lowPct, highPct),
    [result.map, lowPct, highPct],
  );
  const lut = useMemo(
    () =>
      paint === "element" ? buildElementLut(colors(element)) : buildLut(paint),
    [paint, colors, element],
  );

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    canvas.width = w;
    canvas.height = h;
    const image = ctx.createImageData(w, h);
    image.data.set(renderElementMap(result.map, w, h, range, lut));
    ctx.putImageData(image, 0, 0);
  }, [h, lut, range, result.map, w]);

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
            value={paint}
            onChange={(event) => setCmap(event.target.value as MapPaint)}
          >
            {named && <option value="element">{element} colour</option>}
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
            title={
              paint === "element"
                ? `Add to library — the ${element} tint is written to the shared "custom" colormap slot`
                : "Register this map as a derived library image"
            }
            onClick={() => onAddToLibrary(paint)}
          >
            {libraryBusy ? "Adding…" : "Add to library"}
          </button>
        </div>
      </div>

      <div className="fvd-eds-map-canvas-wrap">
        <canvas
          ref={canvasRef}
          title={`${result.e_lo.toFixed(3)}–${result.e_hi.toFixed(3)} keV (${result.bg} background)`}
        />
      </div>
      <MapColorbar lut={lut} lo={range.lo} hi={range.hi} background={result.bg} />
      <footer className="fvd-eds-map-range">
        Data range {formatMapValue(range.dataMin)}–
        {formatMapValue(range.dataMax)}
        {result.bg !== "none" &&
          " · negative pixels are retained and clipped only for display"}
      </footer>
    </section>
  );
}
