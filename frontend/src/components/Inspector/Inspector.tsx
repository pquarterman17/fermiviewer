// Right inspector (handoff §4/§5). Phase 1 skeleton: scene-switched shell
// with the Image metadata card. Phase 2 fills Adjust/Measure/OverlayStyle…

import { useRef, useState } from "react";

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import DiffractionWorkshop from "../workshops/DiffractionWorkshop";
import EdsWorkshop from "../workshops/EdsWorkshop";
import EelsWorkshop from "../workshops/EelsWorkshop";
import AdjustPanel from "./AdjustPanel";
import Card from "./Card";
import ExportCard from "./ExportCard";
import MeasurePanel from "./MeasurePanel";
import ScaleBarCard from "./ScaleBarCard";
import TransformPanel from "./TransformPanel";

const TABS = ["Image", "EELS", "EDS", "Diff"] as const;
type Tab = (typeof TABS)[number];

/** Drag grip on the inspector's left edge — writes the grid's
 *  --right-w CSS variable (checklist N panel resize); persisted. */
function PanelGrip() {
  const drag = useRef<{ startX: number; startW: number } | null>(null);
  const setW = (w: number) => {
    const clamped = Math.min(520, Math.max(220, Math.round(w)));
    document.documentElement.style.setProperty("--right-w", `${clamped}px`);
    localStorage.setItem("fv_right_w", String(clamped));
  };
  return (
    <div
      className="fvd-panel-grip"
      title="Drag to resize the inspector"
      onPointerDown={(e) => {
        const cur = parseInt(
          getComputedStyle(document.documentElement).getPropertyValue(
            "--right-w",
          ) || "280",
          10,
        );
        drag.current = { startX: e.clientX, startW: cur || 280 };
        (e.target as Element).setPointerCapture(e.pointerId);
      }}
      onPointerMove={(e) => {
        if (drag.current) {
          setW(drag.current.startW - (e.clientX - drag.current.startX));
        }
      }}
      onPointerUp={(e) => {
        drag.current = null;
        (e.target as Element).releasePointerCapture(e.pointerId);
      }}
    />
  );
}

// restore the persisted width once at module load
{
  const saved = Number(localStorage.getItem("fv_right_w"));
  if (saved >= 220 && saved <= 520) {
    document.documentElement.style.setProperty("--right-w", `${saved}px`);
  }
}

function fmtPixelSize(meta: ImageMeta): string | null {
  if (meta.pixel_size === null) return null;
  return `${meta.pixel_size.toPrecision(4)} ${meta.pixel_unit}/px`;
}

function fmtEnergy(meta: ImageMeta): string | null {
  if (meta.energy_first === null || meta.energy_last === null) return null;
  return `${meta.energy_first.toFixed(1)} – ${meta.energy_last.toFixed(1)} ${meta.energy_units}`;
}

const KIND_LABEL: Record<ImageMeta["kind"], string> = {
  image: "Image",
  spectrum: "Spectrum",
  spectrum_image: "Spectrum image",
};

export default function Inspector() {
  const meta = useViewer((s) =>
    s.activeId ? (s.images[s.activeId] ?? null) : null,
  );
  const [tab, setTab] = useState<Tab>("Image");

  if (!meta) {
    return (
      <aside className="fvd-inspector">
        <PanelGrip />
        <Card title="Image">
          <div className="fvd-meta-row">
            <span className="k">No image selected</span>
          </div>
        </Card>
      </aside>
    );
  }

  const rows: [string, string][] = [
    ["Name", meta.name],
    ["Kind", KIND_LABEL[meta.kind]],
    ["Shape", meta.shape.join(" × ")],
    ["Dtype", meta.dtype],
  ];
  const px = fmtPixelSize(meta);
  if (px) rows.push(["Pixel size", px]);
  if (meta.n_channels !== null) {
    rows.push(["Channels", String(meta.n_channels)]);
  }
  const en = fmtEnergy(meta);
  if (en) rows.push(["Energy", en]);

  const extra = Object.entries(meta.meta).slice(0, 12);

  return (
    <aside className="fvd-inspector" style={{ position: "relative" }}>
      <PanelGrip />
      <div className="fvd-inspector-tabs">
        <span className="title">INSPECTOR</span>
        <div className="fvd-seg">
          {TABS.map((t) => (
            <button
              key={t}
              className={`fvd-seg-btn${tab === t ? " active" : ""}`}
              onClick={() => setTab(t)}
            >
              {t}
            </button>
          ))}
        </div>
      </div>
      {tab === "EELS" && (
        <Card title="EELS">
          <EelsWorkshop />
        </Card>
      )}
      {tab === "EDS" && (
        <Card title="EDS">
          <EdsWorkshop />
        </Card>
      )}
      {tab === "Diff" && (
        <Card title="Diffraction">
          <DiffractionWorkshop />
        </Card>
      )}
      {tab === "Image" && <MeasurePanel />}
      {tab === "Image" && meta.kind !== "spectrum" && <TransformPanel />}
      {tab === "Image" && meta.kind !== "spectrum" && <AdjustPanel />}
      {tab === "Image" && <ScaleBarCard />}
      {tab === "Image" && meta.kind !== "spectrum" && <ExportCard />}
      {tab === "Image" && (
        <Card title="Image" defaultOpen={false}>
          {rows.map(([k, v]) => (
            <div key={k} className="fvd-meta-row">
              <span className="k">{k}</span>
              <span className="v" title={v}>
                {v}
              </span>
            </div>
          ))}
        </Card>
      )}
      {tab === "Image" && extra.length > 0 && (
        <Card title="Metadata" defaultOpen={false}>
          {extra.map(([k, v]) => (
            <div key={k} className="fvd-meta-row">
              <span className="k">{k}</span>
              <span className="v" title={String(v)}>
                {String(v)}
              </span>
            </div>
          ))}
        </Card>
      )}
    </aside>
  );
}
