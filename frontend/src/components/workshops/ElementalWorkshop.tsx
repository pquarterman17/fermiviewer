// Elemental Analysis — one workspace for EDS and EELS.
//
// The two used to be separate workshop windows, which is how EDS accumulated
// zoom, per-element colours, integration and the Maps workflow while EELS got
// none of them. Sharing a shell makes that divergence structural rather than
// a matter of remembering: Maps and Explore are the same components for both,
// and only Quantify / Model fit swap their internals, because only those are
// genuinely different physics.
//
// The modality is a property of the open cube, resolved by
// resolveSpectralModality (metadata → filename → format → energy range) and
// re-routable from the badge for an ambiguous one.

import { useState } from "react";

import type { EdsQuantResult } from "../../lib/api";
import {
  resolveSpectralModality,
  saveSpectralModality,
  type SpectralModality,
} from "../../lib/spectralModality";
import { useViewer } from "../../store/viewer";
import MapsTab from "../elemental/MapsTab";
import EdsModelFit from "./EdsModelFit";
import EdsQuantifyPanel from "./EdsQuantifyPanel";
import EdsSpectrumImage from "./EdsSpectrumImage";
import EelsWorkshop from "./EelsWorkshop";

type Tab = "maps" | "explore" | "quantify" | "model" | "advanced";

const TABS: { id: Tab; label: string; eelsOnly?: boolean }[] = [
  { id: "maps", label: "Maps" },
  { id: "explore", label: "Explore" },
  { id: "quantify", label: "Quantify" },
  { id: "model", label: "Model fit" },
  { id: "advanced", label: "Advanced", eelsOnly: true },
];

/** Shell tab → the EELS workshop's own tab name. */
const EELS_TAB: Record<Tab, "Explore" | "Quantify" | "Model fit" | "Advanced"> = {
  maps: "Explore",
  explore: "Explore",
  quantify: "Quantify",
  model: "Model fit",
  advanced: "Advanced",
};

export default function ElementalWorkshop() {
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const [tab, setTab] = useState<Tab>("maps");
  const [elements, setElements] = useState("Fe, O");
  const [quant, setQuant] = useState<EdsQuantResult | null>(null);

  // resolveSpectralModality returns the classification AND why, so the badge
  // can explain itself rather than looking like an arbitrary guess.
  const classification = meta ? resolveSpectralModality(meta) : null;
  const modality: SpectralModality = classification?.modality ?? "eds";
  const isEels = modality === "eels";

  // Once Quantify has run, the Maps legend can carry at% instead of raw net
  // counts — the same elements, now with numbers a reader can compare.
  const quantBySymbol = quant
    ? Object.fromEntries(
        quant.elements.map((el, i) => [el, quant.mean_atomic_pct[i]]),
      )
    : undefined;

  const setModality = (next: SpectralModality) => {
    if (meta) saveSpectralModality(meta, next);
  };

  const visible = TABS.filter((t) => !t.eelsOnly || isEels);

  return (
    <div className="fvd-ws fvd-eds-workspace">
      <div className="fvd-elemental-head">
        <div
          className="fvd-eds-workspace-tabs"
          role="tablist"
          aria-label="Elemental Analysis"
        >
          {visible.map(({ id, label }) => (
            <button
              key={id}
              role="tab"
              aria-selected={tab === id}
              className={`fvd-eds-workspace-tab${tab === id ? " active" : ""}`}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </div>
        <label className="fvd-elemental-modality">
          <span className="fvd-visually-hidden">Spectral modality</span>
          <select
            value={modality}
            title={
              classification
                ? `Treated as ${modality.toUpperCase()} (${classification.reason})`
                : "Which spectroscopy this cube is treated as"
            }
            onChange={(e) => setModality(e.target.value as SpectralModality)}
          >
            <option value="eds">EDS</option>
            <option value="eels">EELS</option>
          </select>
        </label>
      </div>

      {isEels ? (
        tab === "maps" ? (
          <div className="fvd-ws-empty">
            <p>
              <strong>Elemental maps are not wired for EELS yet.</strong>
            </p>
            <p>
              The list, montage, overlay and legend are shared and ready; what
              is missing is EELS-side: edge identification (there is no
              equivalent of the EDS auto-assign endpoint), batch edge-map
              extraction returning inline rasters, and a fix to
              <code> calc/eels.extract_map</code>, which still casts the whole
              cube to float64.
            </p>
            <p className="k">
              Use <strong>Explore</strong> for single edge maps meanwhile.
            </p>
          </div>
        ) : (
          <EelsWorkshop tab={EELS_TAB[tab]} />
        )
      ) : (
        <>
          {tab === "maps" && <MapsTab bg="linear" e0Kev={30} quantBySymbol={quantBySymbol} />}
          {tab === "explore" && <EdsSpectrumImage />}
          {tab === "quantify" && (
            <EdsQuantifyPanel
              elements={elements}
              onElements={setElements}
              onResult={setQuant}
            />
          )}
          {tab === "model" && meta && (
            <EdsModelFit activeId={meta.id} elements={elements} />
          )}
        </>
      )}
    </div>
  );
}
