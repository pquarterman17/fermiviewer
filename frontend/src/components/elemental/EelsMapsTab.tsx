// The EELS half of the Maps workflow (SPECTRAL_WORKSPACE_PLAN #3/#12/#16).
//
// Mirrors MapsTab.tsx's identify → confirm → colour-coded maps shape, reusing
// its shared pieces (ElementList, MapMontage, MapOverlay, the figure-export
// path) rather than forking them. Two real differences from EDS: (1)
// /eels/auto-assign scores every tabulated edge server-side, so finding the
// edges needs no client-side spectrum fetch — the sum spectrum fetched here
// (Wave 3) exists only to feed each row's LIVE net, mirroring the same
// liveNetById pattern MapsTab.tsx uses for EDS; (2) one element can carry two
// species at once (Si K and Si L23), so "pick Fe" from the periodic table
// adds/removes every edge auto-assign found for that symbol, not a single
// looked-up line.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { eelsAutoAssign, fetchData16, fetchSpectrum, type Spectrum } from "../../lib/api";
import type { CompositeRaster } from "../../lib/composite";
import { eelsEvidenceFrom, type EelsEdgeEvidence } from "../../lib/elemental/eelsIdentify";
import { exportElementalFigure } from "../../lib/elemental/figureExport";
import type { LegendValue } from "../../lib/elemental/mapLegend";
import { tileKey } from "../../lib/elemental/mapTile";
import {
  compositeName,
  saveCompositeToLibrary,
} from "../../lib/elemental/saveComposite";
import {
  buildRows,
  seedEelsSpeciesFrom,
  visibleSpecies,
  type SpeciesRow,
} from "../../lib/elemental/speciesRows";
import { integrateEdge } from "../../lib/eels/integrate";
import { eelsSpecies } from "../../lib/spectrum/species";
import { speciesOf, useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import ElementList, { type LiveNet } from "./ElementList";
import MapMontage from "./MapMontage";
import MapOverlay from "./MapOverlay";
import { useEelsElementMaps } from "./useEelsMaps";

type View = "both" | "montage" | "overlay";
type Method = "powerlaw" | "exponential";

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
  const ingest = useViewer((s) => s.ingest);
  const byImage = useSpecies((s) => s.byImage);
  const setSpecies = useSpecies((s) => s.setSpecies);
  const addSpecies = useSpecies((s) => s.addSpecies);
  const removeSpecies = useSpecies((s) => s.removeSpecies);
  const setVisible = useSpecies((s) => s.setVisible);
  const setAllVisible = useSpecies((s) => s.setAllVisible);
  const selectedByImage = useSpecies((s) => s.selectedByImage);
  const selectSpecies = useSpecies((s) => s.selectSpecies);
  const species = speciesOf(byImage, activeId);
  const selectedId = activeId ? (selectedByImage[activeId] ?? null) : null;

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
  const sumSpectrum = useRef<Spectrum | null>(null);
  // sumSpectrum lives in a ref so identify()'s synchronous "already fetched?"
  // check doesn't wait a render — but a memo can't depend on a ref's
  // contents, so this counter is bumped every time the ref changes and
  // stands in for it in dependency arrays below. Mirrors MapsTab.tsx (EDS).
  const [spectrumVersion, setSpectrumVersion] = useState(0);
  const overlayCanvas = useRef<HTMLCanvasElement | null>(null);

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

  /** /eels/auto-assign scores every tabulated edge server-side — no spectrum
   *  is needed to find/seed the edges — but the row list's LIVE net (unlike
   *  the frozen identify-time evidence) tracks a window the user just
   *  edited, and that needs the sum spectrum client-side the same way EDS's
   *  identify() fetches one. Cached in sumSpectrum across re-identify. */
  const identify = useCallback(async () => {
    const id = activeId;
    if (!id) return;
    setIdBusy(true);
    try {
      const [auto, raw] = await Promise.all([
        eelsAutoAssign(id, { method }),
        sumSpectrum.current
          ? Promise.resolve(sumSpectrum.current)
          : fetchSpectrum(id),
      ]);
      if (!stillOpen(id)) return;
      sumSpectrum.current = raw;
      setSpectrumVersion((v) => v + 1);
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
    sumSpectrum.current = null;
    setSpectrumVersion((v) => v + 1);
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

  // The spectrum a row's live net is measured against — read through the
  // version counter rather than the ref directly, so this recomputes exactly
  // when the ref's contents change and not on every unrelated re-render.
  const liveSpectrum = useMemo(
    () => sumSpectrum.current,
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [spectrumVersion],
  );

  /** Live net ± σ per row, from the sum spectrum and each species' CURRENT
   *  signal+background windows — unlike `evidence.net`, frozen at the last
   *  identify() pass, this tracks a window the user just edited in Explore
   *  without waiting for a re-ID. A row with no channels in its signal
   *  window (or no spectrum yet) is simply absent here, which ElementList
   *  reads as "nothing live to show" and falls back to the frozen evidence. */
  const liveNetById = useMemo(() => {
    if (!liveSpectrum) return {};
    const out: Record<string, LiveNet | undefined> = {};
    for (const row of rows) {
      const integration = integrateEdge(
        liveSpectrum,
        row.species.windows.signal,
        row.species.windows.background,
        method,
      );
      if (integration) {
        out[row.species.id] = { net: integration.net, sigma: integration.sigma };
      }
    }
    return out;
  }, [liveSpectrum, rows, method]);

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

  const saveComposite = () => {
    const id = activeId;
    if (!id) return;
    saveCompositeToLibrary({
      canvas: overlayCanvas.current,
      parentId: id,
      name: compositeName(
        tiles.map((t) => t.symbol),
        meta?.name,
      ),
      recipe: {
        modality: "eels",
        method,
        channels: tiles.map((t) => ({
          symbol: t.symbol,
          edge: t.line,
          gain: gains[tileKey(t)] ?? 1,
        })),
        legend: legendValue,
        survey: surveyId,
      },
    })
      .then((saved) => {
        if (!saved) {
          report(id, "EELS: no composite to save yet");
          return;
        }
        ingest([saved]);
        report(id, `EELS: "${saved.name}" added to the library`);
      })
      .catch((error: Error) => report(id, `EELS composite: ${error.message}`));
  };

  const exportFigure = () => {
    const id = activeId;
    void exportElementalFigure({
      tiles,
      overlayCanvas: view === "montage" ? null : overlayCanvas.current,
      title: meta?.name ?? "EELS elemental maps",
      filename: "eels-element-maps.png",
      legendValue,
      pixelSize: meta?.pixel_size,
      pixelUnit: meta?.pixel_unit,
    }).then((ok) =>
      report(
        id,
        ok
          ? `EELS: exported figure with ${tiles.length} maps`
          : "EELS: nothing to export yet",
      ),
    );
  };

  return (
    <div className="fvd-eds-maps">
      <ElementList
        rows={rows}
        busy={idBusy}
        liveNetById={liveNetById}
        selectedId={selectedId}
        onToggle={(speciesId, visible) =>
          activeId && setVisible(activeId, speciesId, visible)
        }
        onSetAll={(visible) => activeId && setAllVisible(activeId, visible)}
        onReidentify={() => void identify()}
        onAdd={addElement}
        onRemove={(speciesId) => activeId && removeSpecies(activeId, speciesId)}
        onHover={(symbol) => onHoverElement?.(symbol)}
        onFocus={(row) => {
          // Clicking a row both selects it (for SpeciesChips and any other
          // surface reading the store's selection) and keeps firing the
          // optional montage-tile focus callback — the two are independent
          // consumers of the same click. Mirrors MapsTab.tsx (EDS).
          if (activeId) selectSpecies(activeId, row.species.id);
          onFocusElement?.(row);
        }}
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
          className="fvd-btn"
          style={{ marginLeft: "auto" }}
          disabled={tiles.length === 0 || view === "montage"}
          title="Register the colour overlay as a library image — it reaches the filmstrip, comparison and export like any other image"
          onClick={saveComposite}
        >
          Save to library
        </button>
        <button
          className="fvd-btn primary"
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
        <MapMontage
          tiles={tiles}
          onFocus={(symbol) => {
            const row = rows.find((r) => r.species.symbol === symbol);
            if (row) onFocusElement?.(row);
          }}
        />
      )}

      {view !== "montage" && (
        <MapOverlay
          tiles={tiles}
          gains={gains}
          onGain={(key, gain) => setGains((prev) => ({ ...prev, [key]: gain }))}
          survey={survey}
          surveyOptions={surveyOptions}
          surveyId={surveyId}
          onSurveyId={setSurveyId}
          legendValue={legendValue}
          onLegendValue={setLegendValue}
          canvasRef={overlayCanvas}
        />
      )}
    </div>
  );
}
