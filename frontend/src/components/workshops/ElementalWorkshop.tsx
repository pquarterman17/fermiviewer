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

import { useEffect, useState } from "react";

import type { EdsQuantResult } from "../../lib/api";
import {
  resolveSpectralModality,
  saveSpectralModality,
  useSpectralModalityVersion,
  type SpectralModality,
} from "../../lib/spectralModality";
import { edsSettingsOf, quantElementsOf, useSpecies } from "../../store/species";
import { useViewer } from "../../store/viewer";
import { useResultWorkflow } from "../../store/resultWorkflow";
import EelsMapsTab from "../elemental/EelsMapsTab";
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
  // Per image, defaulting to the identified species (store/species.ts) —
  // it used to be component state seeded with "Fe, O", so Model fit always
  // fitted Fe and O and reopening the workspace forgot the user's list.
  const elements = useSpecies((s) =>
    quantElementsOf(s, meta?.id ?? null, meta?.meta.elements),
  );
  const setElements = (text: string) => {
    if (meta) useSpecies.getState().setQuantElements(meta.id, text);
  };
  // Scoped to the image it was computed on, so switching image never shows
  // (or colours the Maps legend with) another cube's composition.
  const [quant, setQuant] = useState<{
    imageId: string;
    result: EdsQuantResult;
  } | null>(null);
  useSpectralModalityVersion(); // re-render when the EDS/EELS choice changes
  const workflow = useResultWorkflow((s) => s.request);

  useEffect(() => {
    if (workflow?.record.analysis !== "eds.quantify") return;
    if (meta && !workflow.record.source_ids?.includes(meta.id)) {
      useResultWorkflow.getState().clear();
      return;
    }
    if (meta) saveSpectralModality(meta, "eds");
    setTab("quantify");
    const saved = workflow.record.params?.elements;
    if (Array.isArray(saved)) setElements(saved.filter((x): x is string => typeof x === "string").join(", "));
  }, [workflow, meta]);
  // Maps' bg/beam-energy used to be hardcoded here; now they live in the
  // species store, keyed per image, so a later Explore control writing to
  // them (via setEdsSettings) reaches the same values Maps extracts with.
  const edsSettingsByImage = useSpecies((s) => s.edsSettingsByImage);
  const edsSettings = edsSettingsOf(edsSettingsByImage, meta?.id ?? null);

  // resolveSpectralModality returns the classification AND why, so the badge
  // can explain itself rather than looking like an arbitrary guess.
  const classification = meta ? resolveSpectralModality(meta) : null;
  const workflowTargetsSource = workflow?.record.analysis === "eds.quantify" &&
    workflow.record.source_ids?.includes(meta?.id ?? "");
  const modality: SpectralModality = workflowTargetsSource
    ? "eds"
    : classification?.modality ?? "eds";
  const isEels = modality === "eels";

  // Once Quantify has run, the Maps legend can carry at% instead of raw net
  // counts — the same elements, now with numbers a reader can compare.
  const quantHere = quant && quant.imageId === meta?.id ? quant.result : null;
  const quantBySymbol = quantHere
    ? Object.fromEntries(
        quantHere.elements.map((el, i) => [el, quantHere.mean_atomic_pct[i]]),
      )
    : undefined;

  const setModality = (next: SpectralModality) => {
    if (meta) saveSpectralModality(meta, next);
  };

  const visible = TABS.filter((t) => !t.eelsOnly || isEels);
  // Maps identify elements from a spectrum-image cube's sum spectrum; on a
  // 2-D image or single spectrum they can only fail, and used to post that
  // failure to the status bar on every image switch while the window was open.
  const mapsNeedsCube = tab === "maps" && meta?.kind !== "spectrum_image";

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

      {mapsNeedsCube ? (
        <div className="fvd-ws-note">
          Maps need a spectrum-image cube. Select one in the library, or use
          Explore / Quantify for a single spectrum.
        </div>
      ) : isEels ? (
        tab === "maps" ? (
          <EelsMapsTab />
        ) : (
          <EelsWorkshop tab={EELS_TAB[tab]} />
        )
      ) : (
        <>
          {tab === "maps" && (
            <MapsTab
              bg={edsSettings.bg}
              e0Kev={edsSettings.e0Kev}
              quantBySymbol={quantBySymbol}
            />
          )}
          {tab === "explore" && <EdsSpectrumImage />}
          {tab === "quantify" && (
            <EdsQuantifyPanel
              key={meta?.id ?? ""}
              elements={elements}
              onElements={setElements}
              onResult={(r) =>
                setQuant(r && meta ? { imageId: meta.id, result: r } : null)
              }
            />
          )}
          {tab === "model" && meta && (
            <EdsModelFit
              key={meta.id}
              activeId={meta.id}
              elements={elements}
              onElements={setElements}
            />
          )}
        </>
      )}
    </div>
  );
}
