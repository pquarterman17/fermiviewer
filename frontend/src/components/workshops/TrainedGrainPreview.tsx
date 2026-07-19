import type { GrainPreview, GrainPreviewClass } from "../../lib/api";
import { SCRIBBLE_COLORS } from "../../store/scribble";

export function TrainedPreviewLegend({
  classes,
}: {
  classes: GrainPreviewClass[];
}) {
  return (
    <div className="fvd-legend">
      {classes.map((c) => {
        const col = SCRIBBLE_COLORS[(c.class_id - 1) % SCRIBBLE_COLORS.length];
        return (
          <div key={c.class_id} className="fvd-legend-item">
            <span
              className="fvd-legend-chip"
              style={{
                background: c.is_boundary ? "transparent" : col,
                border: c.is_boundary
                  ? "1px dashed var(--text-faint)"
                  : "none",
              }}
            />
            <span className="fvd-legend-label">
              {c.is_boundary ? "∅ " : ""}Class {c.class_id}
            </span>
            <span className="fvd-legend-val">
              {Math.round(c.fraction * 100)}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

export function TrainedGrainPreview({
  preview,
  activeId,
  sourceId,
  show,
}: {
  preview: GrainPreview;
  activeId: string;
  sourceId: string;
  show: (id: string) => void;
}) {
  const confidence = Math.round(preview.mean_confidence * 100);
  const uncertain = Math.round(preview.low_confidence_fraction * 100);
  const threshold = Math.round(preview.confidence_threshold * 100);

  return (
    <>
      <div className="fvd-ws-note">
        pixel classification preview · no grains created yet
      </div>
      <div className="fvd-ws-row" role="group" aria-label="Preview view">
        <button
          className={`fvd-btn${activeId === sourceId ? " active" : ""}`}
          onClick={() => show(sourceId)}
        >
          Source
        </button>
        <button
          className={`fvd-btn${activeId === preview.class_map.id ? " active" : ""}`}
          onClick={() => show(preview.class_map.id)}
        >
          Classes
        </button>
        <button
          className={`fvd-btn${activeId === preview.confidence_map.id ? " active" : ""}`}
          onClick={() => show(preview.confidence_map.id)}
        >
          Confidence
        </button>
      </div>
      <div className="fvd-ws-note">
        mean confidence {confidence}% · {uncertain}% below {threshold}%
      </div>
      <TrainedPreviewLegend classes={preview.classes} />
    </>
  );
}
