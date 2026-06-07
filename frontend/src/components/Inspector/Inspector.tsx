// Right inspector (handoff §4/§5). Phase 1 skeleton: scene-switched shell
// with the Image metadata card. Phase 2 fills Adjust/Measure/OverlayStyle…

import type { ImageMeta } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import AdjustPanel from "./AdjustPanel";
import MeasurePanel from "./MeasurePanel";

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

  if (!meta) {
    return (
      <aside className="fvd-inspector">
        <div className="fvd-card">
          <h3>Image</h3>
          <div className="fvd-meta-row">
            <span className="k">No image selected</span>
          </div>
        </div>
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
    <aside className="fvd-inspector">
      {meta.kind !== "spectrum" && <AdjustPanel />}
      <MeasurePanel />
      <div className="fvd-card">
        <h3>Image</h3>
        {rows.map(([k, v]) => (
          <div key={k} className="fvd-meta-row">
            <span className="k">{k}</span>
            <span className="v" title={v}>
              {v}
            </span>
          </div>
        ))}
      </div>
      {extra.length > 0 && (
        <div className="fvd-card">
          <h3>Metadata</h3>
          {extra.map(([k, v]) => (
            <div key={k} className="fvd-meta-row">
              <span className="k">{k}</span>
              <span className="v" title={String(v)}>
                {String(v)}
              </span>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
