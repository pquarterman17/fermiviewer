// Combined element overlay with its colour legend.
//
// This is the figure people actually publish: every selected element blended
// into one image, optionally over the greyscale survey/HAADF so structure
// shows where nothing is mapped, with a legend naming each colour. The legend
// is not decoration — without it a multi-element overlay is unreadable.

import { useEffect, useMemo, useRef, useState } from "react";

import { compositeChannels, type CompositeRaster } from "../../lib/composite";
import { useElementColors } from "../../lib/elemental/elementColors";
import { formatCountTick } from "../../lib/edsSpectrumDisplay";
import type { MapTile } from "./MapMontage";

export type LegendValue = "none" | "net" | "atomic";

/** Normalize a float map to the 0–65535 the compositor windows against. */
function toRaster(tile: MapTile): CompositeRaster {
  const [h, w] = tile.shape;
  const data = new Uint16Array(w * h);
  let max = 0;
  for (const row of tile.map) {
    for (const v of row) if (Number.isFinite(v) && v > max) max = v;
  }
  const scale = max > 0 ? 65535 / max : 0;
  for (let y = 0; y < h; y++) {
    const row = tile.map[y] ?? [];
    for (let x = 0; x < w; x++) {
      const v = row[x];
      // Negative pixels are real (over-subtracted background) but have no
      // colour to contribute; clamping at zero keeps them from wrapping.
      data[y * w + x] = Number.isFinite(v) && v > 0 ? v * scale : 0;
    }
  }
  return { w, h, data };
}

export default function EdsMapOverlay({
  tiles,
  gains,
  onGain,
  survey,
  surveyOptions,
  surveyId,
  onSurveyId,
  legendValue,
  onLegendValue,
  quantBySymbol,
}: {
  tiles: MapTile[];
  /** Per-element brightness, symbol → 0–2. */
  gains: Record<string, number>;
  onGain: (symbol: string, gain: number) => void;
  /** Greyscale survey / HAADF raster for the chosen underlay image. */
  survey: CompositeRaster | null;
  /** Library images whose spatial size matches the cube. */
  surveyOptions: { id: string; name: string }[];
  surveyId: string | null;
  onSurveyId: (id: string | null) => void;
  legendValue: LegendValue;
  onLegendValue: (value: LegendValue) => void;
  quantBySymbol?: Record<string, number>;
}) {
  const colors = useElementColors();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [blend, setBlend] = useState<"add" | "max">("add");
  const [surveyLevel, setSurveyLevel] = useState(0.45);

  const rasters = useMemo(() => tiles.map(toRaster), [tiles]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx || rasters.length === 0) return;
    const { w, h, rgba } = compositeChannels(
      rasters,
      tiles.map((t) => ({
        color: colors(t.symbol),
        intensity: gains[t.symbol] ?? 1,
        visible: true,
      })),
      blend,
      survey && surveyLevel > 0
        ? { raster: survey, intensity: surveyLevel }
        : undefined,
    );
    canvas.width = w;
    canvas.height = h;
    const image = new ImageData(w, h);
    image.data.set(rgba);
    ctx.putImageData(image, 0, 0);
  }, [blend, colors, gains, rasters, survey, surveyLevel, tiles]);

  if (tiles.length === 0) return null;

  const detail = (symbol: string): string => {
    if (legendValue === "atomic") {
      const pct = quantBySymbol?.[symbol];
      return pct == null ? "" : `${pct.toFixed(1)} at%`;
    }
    if (legendValue === "net") {
      const tile = tiles.find((t) => t.symbol === symbol);
      return tile ? formatCountTick(tile.totalCounts) : "";
    }
    return "";
  };

  return (
    <section className="fvd-eds-overlay" aria-label="Element overlay">
      <div className="fvd-eds-overlay-toolbar">
        <span className="k">Overlay</span>
        <div className="fvd-seg">
          {(["add", "max"] as const).map((mode) => (
            <button
              key={mode}
              className={`fvd-seg-btn${blend === mode ? " active" : ""}`}
              title={
                mode === "max"
                  ? "per-channel max — cleaner where elements overlap"
                  : "additive blend"
              }
              onClick={() => setBlend(mode)}
            >
              {mode}
            </button>
          ))}
        </div>
        <label className="k">
          Legend
          <select
            value={legendValue}
            onChange={(e) => onLegendValue(e.target.value as LegendValue)}
          >
            <option value="none">colour only</option>
            <option value="net">net counts</option>
            <option value="atomic">at%</option>
          </select>
        </label>
        <label className="k" title="Greyscale image drawn beneath the elements">
          Under
          <select
            value={surveyId ?? ""}
            onChange={(e) => onSurveyId(e.target.value || null)}
          >
            <option value="">none</option>
            {surveyOptions.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
        </label>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={surveyLevel}
          disabled={!survey}
          aria-label="Underlay brightness"
          title="Brightness of the survey / HAADF underlay"
          onChange={(e) => setSurveyLevel(Number(e.target.value))}
        />
      </div>

      <div className="fvd-eds-overlay-canvas">
        <canvas ref={canvasRef} />
      </div>

      <ul className="fvd-eds-legend">
        {tiles.map((tile) => {
          const value = detail(tile.symbol);
          return (
            <li key={tile.symbol}>
              <span
                className="fvd-eds-legend-swatch"
                style={{ background: colors(tile.symbol) }}
                aria-hidden="true"
              />
              <span style={{ color: colors(tile.symbol) }}>
                {tile.symbol} {tile.line}α
              </span>
              {value && <span className="k">{value}</span>}
            </li>
          );
        })}
      </ul>

      <details className="fvd-eds-overlay-gains">
        <summary className="k">Per-element brightness</summary>
        {tiles.map((tile) => (
          <div className="fvd-ws-row" key={tile.symbol}>
            <span className="k" style={{ width: 32, color: colors(tile.symbol) }}>
              {tile.symbol}
            </span>
            <input
              type="range"
              min={0}
              max={2}
              step={0.05}
              style={{ flex: 1 }}
              value={gains[tile.symbol] ?? 1}
              aria-label={`Brightness for ${tile.symbol}`}
              onChange={(e) => onGain(tile.symbol, Number(e.target.value))}
            />
            <span className="k" style={{ width: 34, textAlign: "right" }}>
              {(gains[tile.symbol] ?? 1).toFixed(2)}
            </span>
          </div>
        ))}
      </details>
    </section>
  );
}
