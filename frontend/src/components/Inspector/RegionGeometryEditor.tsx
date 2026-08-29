import type {
  ProjectRegion,
  ProjectRegionSet,
  RegionPart,
} from "../../lib/api";
import {
  measureToRegionShape,
  nextRegionId,
  regionShapeSummary,
  regionShapeToMeasure,
} from "../../lib/regionWorkspace";
import { useViewer, type Measure } from "../../store/viewer";

const NO_MEASURES: Measure[] = [];

interface Props {
  imageId: string;
  width: number;
  height: number;
  regionSet: ProjectRegionSet;
  selectedRegion: ProjectRegion | null;
  disabled: boolean;
  onChange: (regionSet: ProjectRegionSet, message: string) => void;
}

export default function RegionGeometryEditor({
  imageId,
  width,
  height,
  regionSet,
  selectedRegion,
  disabled,
  onChange,
}: Props) {
  const measures = useViewer((state) => state.measures[imageId] ?? NO_MEASURES);
  const selectedMeasureId = useViewer((state) => state.selectedMeasure);
  const addMeasure = useViewer((state) => state.addMeasure);
  const setCaptureMode = useViewer((state) => state.setCaptureMode);
  const setStatus = useViewer((state) => state.setStatus);
  const drawing = measures.find((measure) => measure.id === selectedMeasureId) ?? null;
  const shape = drawing ? measureToRegionShape(drawing, width, height) : null;

  const appendPart = (mode: RegionPart["mode"]) => {
    if (!selectedRegion || !shape) return;
    const updated = {
      ...selectedRegion,
      parts: [...selectedRegion.parts, { mode, shape }],
    };
    replaceRegion(regionSet, updated, onChange, `${mode === "include" ? "added a disconnected part to" : "subtracted a drawing from"} “${selectedRegion.name ?? selectedRegion.id}”`);
  };

  return (
    <div className="fvd-region-geometry">
      <div className="fvd-region-geometry-head">
        <div>
          <strong>Drawing source</strong>
          <span>
            {drawing && shape
              ? `${drawing.kind} · ${drawing.pts.length} points${drawing.holes?.length ? ` · ${drawing.holes.length} hole${drawing.holes.length === 1 ? "" : "s"}` : ""}`
              : "Select a polygon, lasso, ROI, or ellipse on the stage"}
          </span>
        </div>
        <button
          className="fvd-btn"
          disabled={disabled || !shape}
          title="Copy the selected stage drawing into this set as an exact canonical region"
          onClick={() => {
            if (!shape) return;
            const id = nextRegionId(
              `region-${regionSet.regions.length + 1}`,
              regionSet.regions.map((region) => region.id),
            );
            onChange({
              ...regionSet,
              regions: [...regionSet.regions, {
                id,
                name: `Region ${regionSet.regions.length + 1}`,
                region_class: null,
                parts: [{ mode: "include", shape }],
                meta: {},
              }],
            }, `added selected drawing as “Region ${regionSet.regions.length + 1}”`);
          }}
        >
          New region
        </button>
      </div>
      <div className="fvd-region-draw-tools" aria-label="Draw analysis region source">
        <span>Draw</span>
        <button onClick={() => setCaptureMode("polygon")}>Polygon</button>
        <button onClick={() => setCaptureMode("lasso")}>Lasso</button>
        <button onClick={() => setCaptureMode("roi")}>Rectangle</button>
        <button onClick={() => setCaptureMode("ellipse")}>Ellipse</button>
      </div>
      <div className="fvd-region-hole-help">
        Hole: draw an inner polygon, right-click it, then choose <strong>Mark as hole</strong>.
      </div>

      {selectedRegion && (
        <>
          <div className="fvd-region-compose-actions">
            <button className="fvd-btn" disabled={disabled || !shape} onClick={() => appendPart("include")}>
              + Disconnected part
            </button>
            <button className="fvd-btn" disabled={disabled || !shape} onClick={() => appendPart("exclude")}>
              − Exclusion
            </button>
          </div>
          <div className="fvd-region-parts" aria-label="Ordered region geometry">
            {selectedRegion.parts.map((part, index) => (
              <PartRow
                key={`${selectedRegion.id}-${index}`}
                part={part}
                index={index}
                parts={selectedRegion.parts}
                drawing={drawing}
                replacement={shape}
                width={width}
                height={height}
                disabled={disabled}
                onEdit={() => {
                  const measure = regionShapeToMeasure(part.shape, width, height);
                  if (!measure) {
                    setStatus("this circle or holed bounded shape cannot be edited on the annotation rails without changing its exact mask");
                    return;
                  }
                  addMeasure(imageId, measure);
                  setStatus(`loaded part ${index + 1} onto the stage — edit it, then choose Replace`);
                }}
                onParts={(parts, message) => replaceRegion(
                  regionSet,
                  { ...selectedRegion, parts },
                  onChange,
                  message,
                )}
              />
            ))}
          </div>
          <div className="fvd-region-order-note">
            Parts apply top to bottom. A later inclusion can add pixels back after an exclusion.
          </div>
        </>
      )}
    </div>
  );
}

function replaceRegion(
  group: ProjectRegionSet,
  updated: ProjectRegion,
  onChange: Props["onChange"],
  message: string,
) {
  onChange({
    ...group,
    regions: group.regions.map((region) => region.id === updated.id ? updated : region),
  }, message);
}

interface PartRowProps {
  part: RegionPart;
  index: number;
  parts: RegionPart[];
  drawing: Measure | null;
  replacement: RegionPart["shape"] | null;
  width: number;
  height: number;
  disabled: boolean;
  onEdit: () => void;
  onParts: (parts: RegionPart[], message: string) => void;
}

function PartRow(props: PartRowProps) {
  const { part, index, parts } = props;
  const canEdit = regionShapeToMeasure(part.shape, props.width, props.height) != null;
  const canMoveUp = index > 1 || (index === 1 && part.mode === "include");
  const canMoveDown = index < parts.length - 1 && !(index === 0 && parts[1]?.mode === "exclude");
  const updateAt = (updated: RegionPart, message: string) => {
    props.onParts(parts.map((entry, at) => at === index ? updated : entry), message);
  };
  const move = (to: number) => {
    const reordered = [...parts];
    const [moving] = reordered.splice(index, 1);
    reordered.splice(to, 0, moving);
    props.onParts(reordered, `moved part ${index + 1} to position ${to + 1}`);
  };

  return (
    <div className="fvd-region-part-row">
      <span className="fvd-region-part-index">{index + 1}</span>
      <div className="fvd-region-part-main">
        <select
          aria-label={`Part ${index + 1} operation`}
          value={part.mode}
          disabled={props.disabled || index === 0}
          title={index === 0 ? "A region must begin with an inclusion" : "How this shape combines with the mask above it"}
          onChange={(event) => updateAt(
            { ...part, mode: event.target.value as RegionPart["mode"] },
            `changed part ${index + 1} to ${event.target.value}`,
          )}
        >
          <option value="include">Include</option>
          <option value="exclude">Exclude</option>
        </select>
        <span>{part.shape.kind} · {regionShapeSummary(part.shape)}</span>
      </div>
      <button className="fvd-icon-btn" aria-label={`Move part ${index + 1} up`} disabled={props.disabled || !canMoveUp} onClick={() => move(index - 1)}>↑</button>
      <button className="fvd-icon-btn" aria-label={`Move part ${index + 1} down`} disabled={props.disabled || !canMoveDown} onClick={() => move(index + 1)}>↓</button>
      <button className="fvd-icon-btn" aria-label={`Edit part ${index + 1} on stage`} title={canEdit ? "Copy this exact shape to the stage annotation editor" : "Exact circle or bounded shape with holes cannot be represented by the annotation editor"} disabled={props.disabled || !canEdit} onClick={props.onEdit}>✎</button>
      <button
        className="fvd-icon-btn"
        aria-label={`Replace part ${index + 1} from selected drawing`}
        title={props.drawing ? `Replace from selected ${props.drawing.kind}` : "Select a compatible stage drawing first"}
        disabled={props.disabled || !props.replacement}
        onClick={() => props.replacement && updateAt(
          { ...part, shape: props.replacement },
          `replaced part ${index + 1} from the selected drawing`,
        )}
      >
        ↻
      </button>
      <button
        className="fvd-icon-btn fvd-region-danger"
        aria-label={`Remove part ${index + 1}`}
        title={index === 0 ? "Replace the first inclusion or delete the whole region" : "Remove this part"}
        disabled={props.disabled || index === 0}
        onClick={() => props.onParts(parts.filter((_, at) => at !== index), `removed part ${index + 1}`)}
      >
        ✕
      </button>
    </div>
  );
}
