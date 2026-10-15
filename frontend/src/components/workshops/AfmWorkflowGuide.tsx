import { useEffect, useRef, useState } from "react";

import {
  afmMap,
  renderUrl,
  THUMB_MAX_DIM,
  type AfmLevel,
  type AfmRoi,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";

type MapKind = "psd" | "acf";

const LEVEL_COPY: Record<AfmLevel, string> = {
  none: "Use the measured heights as-is",
  plane: "Remove tilt with a least-squares plane",
  quadratic: "Remove broad scanner bow or curvature",
};

interface MapOutput {
  id: string;
  name: string;
  key: string;
}

export default function AfmWorkflowGuide({
  sourceId,
  sourceName,
  regionLabel,
  roi,
  level,
  analysisKey,
  analysisReady,
  analysisStale,
}: {
  sourceId: string;
  sourceName: string;
  regionLabel: string;
  roi: AfmRoi | null;
  level: AfmLevel;
  analysisKey: string;
  analysisReady: boolean;
  analysisStale: boolean;
}) {
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const setActive = useViewer((s) => s.setActive);
  const openTool = useViewer((s) => s.openTool);
  const ingestDerived = useViewer((s) => s.ingestDerived);
  const setStatus = useViewer((s) => s.setStatus);
  const [busyMap, setBusyMap] = useState<MapKind | null>(null);
  const [maps, setMaps] = useState<Partial<Record<MapKind, MapOutput>>>({});
  const [mapMessage, setMapMessage] = useState<{ error: boolean; text: string } | null>(null);
  const request = useRef(0);

  useEffect(() => {
    request.current += 1;
    setMaps({});
    setBusyMap(null);
    setMapMessage(null);
  }, [sourceId]);
  useEffect(() => () => {
    request.current += 1;
  }, []);

  const drawRegion = () => {
    setActive(sourceId);
    setCaptureMode("roi");
    setStatus("Draw a rectangular ROI, then choose Selected ROI in Surface Analysis");
  };

  const openForSource = (kind: "afmstep" | "surface" | "afmforce") => {
    setActive(sourceId);
    openTool(kind);
  };

  const createMap = (kind: MapKind) => {
    const token = ++request.current;
    const current = () => token === request.current;
    setBusyMap(kind);
    const label = kind === "psd" ? "2-D power spectrum" : "autocorrelation";
    setMapMessage({ error: false, text: `Creating ${label}…` });
    setStatus(`${label}…`);
    afmMap(sourceId, kind, { level, roi })
      .then((meta) => {
        if (!current()) return;
        ingestDerived([meta]);
        // Derived-image ingestion normally selects its output. Keep this
        // guided workflow anchored to the source; the map remains in Library.
        setActive(sourceId);
        setMaps((current) => ({
          ...current,
          [kind]: { id: meta.id, name: meta.name, key: analysisKey },
        }));
        setMapMessage({ error: false, text: `${label} created in Library` });
        setStatus(`${label} created in Library`);
      })
      .catch((error: Error) => {
        if (current()) {
          setMapMessage({ error: true, text: `${label}: ${error.message}` });
          setStatus(`${label}: ${error.message}`);
        }
      })
      .finally(() => {
        if (current()) setBusyMap(null);
      });
  };

  return (
    <section className="fvd-afm-workflow" aria-labelledby="afm-workflow-title">
      <div className="fvd-afm-section-head">
        <div>
          <h3 id="afm-workflow-title">Analysis path</h3>
          <span>Keep the source visible while moving from preparation to interpretation</span>
        </div>
      </div>
      <div className="fvd-afm-workflow-rail">
        <WorkflowStep number="1" label="Source" value={sourceName} />
        <WorkflowStep number="2" label="Region" value={regionLabel} />
        <WorkflowStep number="3" label="Background" value={LEVEL_COPY[level]} />
        <WorkflowStep
          number="4"
          label="Results"
          value={analysisStale ? "Update required" : analysisReady ? "Current" : "Not analyzed"}
          state={analysisStale ? "warning" : analysisReady ? "ready" : undefined}
        />
      </div>
      <div className="fvd-afm-workflow-actions">
        <button type="button" className="fvd-btn" onClick={drawRegion}>Draw ROI</button>
        <span>Draw on the source, then choose <strong>Selected ROI</strong> below.</span>
      </div>

      <div className="fvd-afm-derived">
        <div>
          <strong>Spatial maps</strong>
          <span>Use this region and background removal; outputs are added to Library.</span>
        </div>
        {(["psd", "acf"] as const).map((kind) => {
          const output = maps[kind];
          const current = output?.key === analysisKey;
          return (
            <div className="fvd-afm-derived-action" key={kind}>
              {output && (
                <img
                  src={renderUrl(output.id, { maxDim: THUMB_MAX_DIM })}
                  alt={`${kind === "psd" ? "2-D PSD" : "ACF"} map preview`}
                />
              )}
              <button
                type="button"
                className="fvd-btn"
                disabled={busyMap !== null}
                onClick={() => createMap(kind)}
              >
                {busyMap === kind
                  ? "Creating…"
                  : `${output ? "Regenerate" : "Create"} ${kind === "psd" ? "2-D PSD" : "ACF"}`}
              </button>
              {output && (
                <span title={output.name}>
                  <strong>{output.name}</strong>
                  <em className={current ? "ready" : "stale"}>
                    {current ? "Ready in Library" : "Settings changed"}
                  </em>
                </span>
              )}
            </div>
          );
        })}
      </div>
      {mapMessage && (
        <p className="fvd-afm-map-message" role={mapMessage.error ? "alert" : "status"}>
          {mapMessage.text}
        </p>
      )}

      <div className="fvd-afm-next" aria-label="Continue AFM analysis">
        <span>Continue with</span>
        <button type="button" onClick={() => openForSource("afmstep")}>Step height</button>
        <button
          type="button"
          title="Opens the original height map; ROI and background removal are not applied"
          onClick={() => openForSource("surface")}
        >
          Raw source in 3-D
        </button>
        <button type="button" onClick={() => openForSource("afmforce")}>Force curves</button>
      </div>
    </section>
  );
}

function WorkflowStep({
  number, label, value, state,
}: {
  number: string;
  label: string;
  value: string;
  state?: "ready" | "warning";
}) {
  return (
    <div className={`fvd-afm-workflow-step${state ? ` ${state}` : ""}`}>
      <span className="n">{number}</span>
      <span className="k">{label}</span>
      <span className="v" title={value}>{value}</span>
    </div>
  );
}
