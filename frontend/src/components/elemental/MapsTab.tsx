// The Maps workflow: identify → confirm → colour-coded maps.
//
// Opening a cube identifies its elements and shows them as a checkable list.
// Ticking elements produces a montage of single-element maps plus a combined
// overlay with a colour legend, and one button exports the assembled figure.
// This is the path the workspace is built around; Explore remains for tuning
// a single window by hand.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  edsAutoAssign,
  edsLineEnergy,
  fetchData16,
  fetchSpectrum,
  type Spectrum,
} from "../../lib/api";
import type { CompositeRaster } from "../../lib/composite";
import { elementColor } from "../../lib/elemental/elementColors";
import { renderFigure, type FigureSource } from "../../lib/elemental/figure";
import {
  identifyElements,
  measureElement,
  type IdentifiedElement,
} from "../../lib/elemental/identify";
import { buildElementLut } from "../../lib/elemental/elementColors";
import { normalizeEdsSpectrum } from "../../lib/edsSpectrumDisplay";
import { mapDisplayRange, renderElementMap } from "../../lib/edsMapDisplay";
import { useViewer } from "../../store/viewer";
import EdsElementList from "./ElementList";
import EdsMapMontage, { type MapTile } from "./MapMontage";
import EdsMapOverlay, { type LegendValue } from "./MapOverlay";
import type { EdsMapBackground } from "../workshops/useEdsElementMap";
import { useEdsElementMaps } from "./useElementMaps";

type View = "both" | "montage" | "overlay";

function tileToFigureSource(tile: MapTile, detail: string): FigureSource {
  const [h, w] = tile.shape;
  const color = elementColor(tile.symbol);
  const range = mapDisplayRange(tile.map, 1, 99);
  return {
    label: `${tile.symbol} ${tile.line}α`,
    color,
    detail,
    rgba: renderElementMap(tile.map, w, h, range, buildElementLut(color)),
    w,
    h,
  };
}

export default function EdsMapsTab({
  bg,
  e0Kev,
  quantBySymbol,
  onFocusElement,
  onHoverElement,
}: {
  bg: EdsMapBackground;
  e0Kev: number;
  quantBySymbol?: Record<string, number>;
  /** Frame this element's window on the Explore spectrum. */
  onFocusElement?: (element: IdentifiedElement) => void;
  onHoverElement?: (symbol: string | null) => void;
}) {
  const activeId = useViewer((s) => s.activeId);
  const images = useViewer((s) => s.images);
  const setStatus = useViewer((s) => s.setStatus);

  const [elements, setElements] = useState<IdentifiedElement[]>([]);
  const [idBusy, setIdBusy] = useState(false);
  const [view, setView] = useState<View>("both");
  const [gains, setGains] = useState<Record<string, number>>({});
  const [legendValue, setLegendValue] = useState<LegendValue>("net");
  const [surveyId, setSurveyId] = useState<string | null>(null);
  const [survey, setSurvey] = useState<CompositeRaster | null>(null);
  const sumSpectrum = useRef<Spectrum | null>(null);

  const stillOpen = useCallback(
    (id: string | null): id is string =>
      !!id && !!useViewer.getState().images[id],
    [],
  );
  const report = useCallback(
    (id: string | null, message: string) => {
      if (stillOpen(id)) setStatus(message);
    },
    [setStatus, stillOpen],
  );

  const meta = activeId ? images[activeId] : null;
  const cubeShape = meta?.shape;

  /** Identify from the whole-cube spectrum; the cube's own sum is the only
   *  spectrum with enough counts to judge a trace element against noise. */
  const identify = useCallback(async () => {
    const id = activeId;
    if (!id) return;
    setIdBusy(true);
    try {
      const [auto, raw] = await Promise.all([
        edsAutoAssign(id),
        sumSpectrum.current
          ? Promise.resolve(sumSpectrum.current)
          : fetchSpectrum(id),
      ]);
      if (!stillOpen(id)) return;
      sumSpectrum.current = raw;
      const spectrum = normalizeEdsSpectrum(raw);
      const found = identifyElements(auto, spectrum, { background: bg, e0Kev });
      setElements(found);
      const shown = found.filter((e) => e.selected).length;
      report(
        id,
        found.length === 0
          ? "EDS: no elements identified — add them manually"
          : `EDS: identified ${found.length} element${
              found.length === 1 ? "" : "s"
            }, ${shown} above trace`,
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      report(id, `EDS identify: ${message}`);
    } finally {
      setIdBusy(false);
    }
  }, [activeId, bg, e0Kev, report, stillOpen]);

  // Auto-ID when a cube becomes active: the user should never face a blank
  // element box on a dataset whose elements are sitting in its own spectrum.
  useEffect(() => {
    sumSpectrum.current = null;
    setElements([]);
    setGains({});
    setSurveyId(null);
    setSurvey(null);
    if (activeId) void identify();
    // identify() changes identity with bg/e0Kev; re-running on those would
    // re-identify mid-session and discard the user's ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const { tiles, mapsBusy } = useEdsElementMaps({
    imageId: activeId,
    elements,
    bg,
    e0Kev,
    isOpen: stillOpen,
    onStatus: report,
  });

  // Any 2-D library image matching the cube's spatial footprint can sit under
  // the overlay — a HAADF survey loaded alongside, or a derived map.
  const surveyOptions = useMemo(() => {
    if (!cubeShape) return [];
    const [h, w] = cubeShape;
    return Object.values(images)
      .filter(
        (image) =>
          image.id !== activeId &&
          image.kind !== "spectrum_image" &&
          image.shape?.[0] === h &&
          image.shape?.[1] === w,
      )
      .map((image) => ({ id: image.id, name: image.name ?? image.id }));
  }, [activeId, cubeShape, images]);

  useEffect(() => {
    if (!surveyId) {
      setSurvey(null);
      return;
    }
    let stale = false;
    fetchData16(surveyId)
      .then((raster) => {
        if (!stale) setSurvey(raster);
      })
      .catch((error: Error) => report(activeId, `EDS underlay: ${error.message}`));
    return () => {
      stale = true;
    };
  }, [activeId, report, surveyId]);

  const setSelected = (symbol: string, selected: boolean) =>
    setElements((prev) =>
      prev.map((e) => (e.symbol === symbol ? { ...e, selected } : e)),
    );

  const addElement = (symbol: string) => {
    const spectrum = sumSpectrum.current;
    if (!spectrum || elements.some((e) => e.symbol === symbol)) return;
    edsLineEnergy(symbol)
      .then(({ energy_kev, line }) => {
        const measured = measureElement(
          symbol,
          line,
          energy_kev,
          normalizeEdsSpectrum(spectrum),
          elements,
          { background: bg, e0Kev },
        );
        if (measured) setElements((prev) => [...prev, measured]);
      })
      .catch((error: Error) => report(activeId, `EDS add: ${error.message}`));
  };

  const exportFigure = () => {
    if (tiles.length === 0) return;
    const detailOf = (symbol: string) => {
      if (legendValue === "atomic") {
        const pct = quantBySymbol?.[symbol];
        return pct == null ? "" : `${pct.toFixed(1)} at%`;
      }
      return "";
    };
    const sources = tiles.map((tile) =>
      tileToFigureSource(tile, detailOf(tile.symbol)),
    );
    const overlayCanvas = document.querySelector<HTMLCanvasElement>(
      ".fvd-eds-overlay-canvas canvas",
    );
    let overlay: FigureSource | undefined;
    if (overlayCanvas) {
      const ctx = overlayCanvas.getContext("2d");
      const data = ctx?.getImageData(
        0,
        0,
        overlayCanvas.width,
        overlayCanvas.height,
      );
      if (data) {
        overlay = {
          label: "Overlay",
          color: "#e6e8ee",
          rgba: data.data,
          w: overlayCanvas.width,
          h: overlayCanvas.height,
        };
      }
    }
    const canvas = document.createElement("canvas");
    renderFigure(canvas, sources, {
      title: meta?.name ?? "Elemental maps",
      overlay,
      columns: Math.min(4, Math.max(2, Math.ceil(Math.sqrt(tiles.length + 1)))),
    });
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "eds-element-maps.png";
      anchor.click();
      URL.revokeObjectURL(url);
      report(activeId, `EDS: exported figure with ${tiles.length} maps`);
    }, "image/png");
  };

  return (
    <div className="fvd-eds-maps">
      <EdsElementList
        elements={elements}
        busy={idBusy}
        quantBySymbol={quantBySymbol}
        onToggle={setSelected}
        onSetAll={(selected) =>
          setElements((prev) => prev.map((e) => ({ ...e, selected })))
        }
        onReidentify={() => void identify()}
        onAdd={addElement}
        onRemove={(symbol) =>
          setElements((prev) => prev.filter((e) => e.symbol !== symbol))
        }
        onHover={(symbol) => onHoverElement?.(symbol)}
        onFocus={(element) => onFocusElement?.(element)}
      />

      <div className="fvd-ws-row">
        <div className="fvd-seg">
          {(["both", "montage", "overlay"] as const).map((mode) => (
            <button
              key={mode}
              className={`fvd-seg-btn${view === mode ? " active" : ""}`}
              onClick={() => setView(mode)}
            >
              {mode}
            </button>
          ))}
        </div>
        <span className="k">
          {mapsBusy ? "Extracting maps…" : `${tiles.length} maps`}
        </span>
        <button
          className="fvd-btn primary"
          style={{ marginLeft: "auto" }}
          disabled={tiles.length === 0}
          title="Export the montage, overlay and legend as one figure"
          onClick={exportFigure}
        >
          Export figure
        </button>
      </div>

      {tiles.length === 0 && !mapsBusy && (
        <div className="fvd-ws-empty">
          Tick elements above to extract their maps.
        </div>
      )}

      {view !== "overlay" && (
        <EdsMapMontage
          tiles={tiles}
          onFocus={(symbol) => {
            const element = elements.find((e) => e.symbol === symbol);
            if (element) onFocusElement?.(element);
          }}
        />
      )}

      {view !== "montage" && (
        <EdsMapOverlay
          tiles={tiles}
          gains={gains}
          onGain={(symbol, gain) =>
            setGains((prev) => ({ ...prev, [symbol]: gain }))
          }
          survey={survey}
          surveyOptions={surveyOptions}
          surveyId={surveyId}
          onSurveyId={setSurveyId}
          legendValue={legendValue}
          onLegendValue={setLegendValue}
          quantBySymbol={quantBySymbol}
        />
      )}
    </div>
  );
}
