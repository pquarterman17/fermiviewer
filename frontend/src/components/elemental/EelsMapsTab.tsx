// The EELS half of the Maps workflow (SPECTRAL_WORKSPACE_PLAN #3/#12/#16).
//
// Mirrors MapsTab.tsx's identify → confirm → colour-coded maps shape, reusing
// its shared pieces (ElementList, MapMontage, MapOverlay, the figure-export
// path) rather than forking them. The two real differences from EDS: (1)
// /eels/auto-assign scores every tabulated edge server-side, so there is no
// client-side spectrum re-fetch/re-integration to do — identify() is one
// request; (2) one element can carry two species at once (Si K and Si L23),
// so "pick Fe" from the periodic table adds/removes every edge auto-assign
// found for that symbol, not a single looked-up line.

import { useCallback, useEffect, useMemo, useState } from "react";

import { eelsAutoAssign, fetchData16 } from "../../lib/api";
import type { CompositeRaster } from "../../lib/composite";
import { buildElementLut, elementColor } from "../../lib/elemental/elementColors";
import { eelsEvidenceFrom, type EelsEdgeEvidence } from "../../lib/elemental/eelsIdentify";
import { renderFigure, type FigureSource } from "../../lib/elemental/figure";
import {
  buildRows,
  seedEelsSpeciesFrom,
  visibleSpecies,
  type SpeciesRow,
} from "../../lib/elemental/speciesRows";
import { mapDisplayRange, renderElementMap } from "../../lib/edsMapDisplay";
import { eelsSpecies } from "../../lib/spectrum/species";
import { speciesOf, useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import EdsElementList from "./ElementList";
import EdsMapMontage, { type MapTile } from "./MapMontage";
import EdsMapOverlay, { type LegendValue } from "./MapOverlay";
import { useEelsElementMaps } from "./useEelsMaps";

type View = "both" | "montage" | "overlay";
type Method = "powerlaw" | "exponential";

function tileToFigureSource(tile: MapTile): FigureSource {
  const [h, w] = tile.shape;
  const color = elementColor(tile.symbol);
  const range = mapDisplayRange(tile.map, 1, 99);
  return {
    label: tile.caption ?? `${tile.symbol} ${tile.line}`,
    color,
    rgba: renderElementMap(tile.map, w, h, range, buildElementLut(color)),
    w,
    h,
  };
}

export default function EelsMapsTab({
  onFocusElement,
  onHoverElement,
}: {
  /** Frame this species' window on the EELS spectrum, once that surface can
   *  consume it. Unwired for now: the spectrum view lives in EelsWorkshop,
   *  developed separately — see the module header. */
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

  // EVIDENCE ONLY — what the user decided lives in the species store, keyed
  // by image, so it survives switching cubes and a re-identification.
  const [evidence, setEvidence] = useState<EelsEdgeEvidence[]>([]);
  const [idBusy, setIdBusy] = useState(false);
  const [method, setMethod] = useState<Method>("powerlaw");
  const [view, setView] = useState<View>("both");
  const [gains, setGains] = useState<Record<string, number>>({});
  const [legendValue, setLegendValue] = useState<LegendValue>("net");
  const [surveyId, setSurveyId] = useState<string | null>(null);
  const [survey, setSurvey] = useState<CompositeRaster | null>(null);

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

  /** /eels/auto-assign scores every tabulated edge server-side, so unlike
   *  EDS's identify() there is no spectrum to fetch or re-integrate here. */
  const identify = useCallback(async () => {
    const id = activeId;
    if (!id) return;
    setIdBusy(true);
    try {
      const auto = await eelsAutoAssign(id, { method });
      if (!stillOpen(id)) return;
      const found = eelsEvidenceFrom(auto);
      setEvidence(found);
      // Seed only when this image has no species yet — a return visit or a
      // re-ID must leave the user's decisions alone.
      const seeded = seedEelsSpeciesFrom(found, speciesOf(useSpecies.getState().byImage, id));
      if (seeded) setSpecies(id, seeded);
      const current = seeded ?? speciesOf(useSpecies.getState().byImage, id);
      const shown = current.filter((sp) => sp.visible).length;
      report(
        id,
        found.length === 0
          ? "EELS: no edges identified — add them manually"
          : `EELS: identified ${found.length} edge${
              found.length === 1 ? "" : "s"
            }, ${shown} showing${seeded ? " (above trace)" : " (your list)"}`,
      );
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : String(error);
      report(id, `EELS identify: ${message}`);
    } finally {
      setIdBusy(false);
    }
  }, [activeId, method, report, stillOpen]);

  // Auto-ID when a cube becomes active: the user should never face a blank
  // edge box on a dataset whose edges are sitting in its own spectrum.
  useEffect(() => {
    setEvidence([]);
    setGains({});
    setSurveyId(null);
    setSurvey(null);
    if (activeId) void identify();
    // identify() changes identity with `method`; re-running on that would
    // re-identify mid-session and discard the user's ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);

  const rows = useMemo(() => buildRows(species, evidence), [species, evidence]);
  const shownSpecies = useMemo(() => visibleSpecies(rows), [rows]);

  const { tiles, mapsBusy } = useEelsElementMaps({
    imageId: activeId,
    species: shownSpecies,
    method,
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
      .catch((error: Error) => report(activeId, `EELS underlay: ${error.message}`));
    return () => {
      stale = true;
    };
  }, [activeId, report, surveyId]);

  /** Picking an element in the table toggles ALL its edges at once: if any
   *  species with that symbol is showing, every one of them is removed;
   *  otherwise every edge auto-assign found for it (there is no separate
   *  single-edge lookup the way EDS has edsLineEnergy — the last identify
   *  pass already scored every in-range edge, so it IS the lookup). */
  const addElement = (symbol: string) => {
    const id = activeId;
    if (!id) return;
    const existingForSymbol = species.filter((sp) => sp.symbol === symbol);
    if (existingForSymbol.length > 0) {
      existingForSymbol.forEach((sp) => removeSpecies(id, sp.id));
      return;
    }
    const matches = evidence.filter((e) => e.symbol === symbol);
    if (matches.length === 0) {
      report(id, `EELS: no ${symbol} edge in this cube's energy range`);
      return;
    }
    matches.forEach((e) =>
      addSpecies(
        id,
        eelsSpecies(e.symbol, e.transition, e.energy, {
          visible: true,
          windows: {
            signal: { lo: e.windowLo, hi: e.windowHi },
            background: { lo: e.fitWindow[0], hi: e.fitWindow[1] },
          },
        }),
      ),
    );
  };

  const exportFigure = () => {
    if (tiles.length === 0) return;
    const sources = tiles.map(tileToFigureSource);
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
      title: meta?.name ?? "EELS elemental maps",
      overlay,
      columns: Math.min(4, Math.max(2, Math.ceil(Math.sqrt(tiles.length + 1)))),
    });
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "eels-element-maps.png";
      anchor.click();
      URL.revokeObjectURL(url);
      report(activeId, `EELS: exported figure with ${tiles.length} maps`);
    }, "image/png");
  };

  return (
    <div className="fvd-eds-maps">
      <EdsElementList
        rows={rows}
        busy={idBusy}
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
        <label className="k" title="Pre-edge background fit model">
          Fit
          <select value={method} onChange={(e) => setMethod(e.target.value as Method)}>
            <option value="powerlaw">power law</option>
            <option value="exponential">exponential</option>
          </select>
        </label>
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
          Tick edges above to extract their maps.
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
          onGain={(key, gain) => setGains((prev) => ({ ...prev, [key]: gain }))}
          survey={survey}
          surveyOptions={surveyOptions}
          surveyId={surveyId}
          onSurveyId={setSurveyId}
          legendValue={legendValue}
          onLegendValue={setLegendValue}
        />
      )}
    </div>
  );
}
