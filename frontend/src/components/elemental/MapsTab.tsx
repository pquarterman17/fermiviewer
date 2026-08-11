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
import {
  buildRows,
  seedSpeciesFrom,
  visibleSpecies,
  type SpeciesRow,
} from "../../lib/elemental/speciesRows";
import { edsSpecies } from "../../lib/spectrum/species";
import { speciesOf, useSpecies } from "../../store/species";
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
  /** Frame this species' window on the Explore spectrum. */
  onFocusElement?: (row: SpeciesRow) => void;
  onHoverElement?: (symbol: string | null) => void;
}) {
  const activeId = useViewer((s) => s.activeId);
  const images = useViewer((s) => s.images);
  const setStatus = useViewer((s) => s.setStatus);
  const byImage = useSpecies((s) => s.byImage);
  const setSpecies = useSpecies((s) => s.setSpecies);
  const addSpecies = useSpecies((s) => s.addSpecies);
  const removeSpecies = useSpecies((s) => s.removeSpecies);
  const setVisible = useSpecies((s) => s.setVisible);
  const setAllVisible = useSpecies((s) => s.setAllVisible);
  const species = speciesOf(byImage, activeId);

  // EVIDENCE ONLY. What the user decided lives in the species store, keyed by
  // image, so it survives switching cubes and a re-identification.
  const [evidence, setEvidence] = useState<IdentifiedElement[]>([]);
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
      setEvidence(found);
      // Seed only when this image has no species yet. On a return visit, or a
      // re-ID, the user's decisions win and only the measured numbers refresh.
      const seeded = seedSpeciesFrom(found, speciesOf(useSpecies.getState().byImage, id));
      if (seeded) setSpecies(id, seeded);
      const current = seeded ?? speciesOf(useSpecies.getState().byImage, id);
      const shown = current.filter((sp) => sp.visible).length;
      report(
        id,
        found.length === 0
          ? "EDS: no elements identified — add them manually"
          : `EDS: identified ${found.length} element${
              found.length === 1 ? "" : "s"
            }, ${shown} showing${seeded ? " (above trace)" : " (your list)"}`,
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
    setEvidence([]);
    setGains({});
    setSurveyId(null);
    setSurvey(null);
    if (activeId) void identify();
    // identify() changes identity with bg/e0Kev; re-running on those would
    // re-identify mid-session and discard the user's ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const rows = useMemo(() => buildRows(species, evidence), [species, evidence]);
  const shownSpecies = useMemo(() => visibleSpecies(rows), [rows]);

  const { tiles, mapsBusy } = useEdsElementMaps({
    imageId: activeId,
    species: shownSpecies,
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

  /** Picking an element in the table toggles it: already on the list → remove,
   *  otherwise measure it against the spectrum and add it. Matches what the
   *  multi-select picker looks like it does. */
  const addElement = (symbol: string) => {
    const id = activeId;
    if (!id) return;
    const existing = species.find((sp) => sp.symbol === symbol);
    if (existing) {
      removeSpecies(id, existing.id);
      return;
    }
    const spectrum = sumSpectrum.current;
    if (!spectrum) return;
    edsLineEnergy(symbol)
      .then(({ energy_kev, line }) => {
        if (!stillOpen(id)) return;
        addSpecies(id, edsSpecies(symbol, line, energy_kev));
        // Measure it too, so the new row shows net and confidence like the
        // identified ones rather than a blank strength bar.
        const measured = measureElement(
          symbol, line, energy_kev,
          normalizeEdsSpectrum(spectrum), evidence,
          { background: bg, e0Kev },
        );
        if (measured) setEvidence((prev) => [...prev, measured]);
      })
      .catch((error: Error) => report(id, `EDS add: ${error.message}`));
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
        rows={rows}
        busy={idBusy}
        quantBySymbol={quantBySymbol}
        onToggle={(speciesId, visible) =>
          activeId && setVisible(activeId, speciesId, visible)
        }
        onSetAll={(visible) => activeId && setAllVisible(activeId, visible)}
        onReidentify={() => void identify()}
        onAdd={addElement}
        onRemove={(speciesId) => activeId && removeSpecies(activeId, speciesId)}
        onHover={(symbol) => onHoverElement?.(symbol)}
        onFocus={(row) => onFocusElement?.(row)}
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
          Tick species above to extract their maps.
        </div>
      )}

      {view !== "overlay" && (
        <EdsMapMontage
          tiles={tiles}
          onFocus={(symbol) => {
            const row = rows.find((r) => r.species.symbol === symbol);
            if (row) onFocusElement?.(row);
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
