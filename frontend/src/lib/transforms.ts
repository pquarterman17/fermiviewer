// Run a transform/filter tool against the active image. Shared by the
// Tools card and the unified ToolsBrowser so the run behaviour stays
// identical. Store-singleton pattern (like stageOps): reads/writes the
// viewer store directly rather than taking props.

import { applyFilter } from "./api";
import type { ParamField, ParamValues } from "./params";
import { applyGeometry, cropToRoi, type GeometryKind } from "./stageOps";
import type { TransformTool } from "./transformTools";
import { useViewer } from "../store/viewer";

/** Parameterless geometry/crop go straight through their stageOps helpers
 *  (undoable, status-reporting); parameterised filters POST /filter and
 *  ingest the derived image. */
export function runTransform(tool: TransformTool, params: ParamValues): void {
  const s = useViewer.getState();
  const id = s.activeId;
  if (!id) return;
  if (tool.via === "geometry") {
    applyGeometry(tool.kind as GeometryKind);
    return;
  }
  if (tool.via === "crop") {
    cropToRoi();
    return;
  }
  s.setStatus(`${tool.label}…`);
  applyFilter(id, tool.kind, params as Record<string, unknown>)
    .then((m) => {
      s.ingestDerived([m]);
      s.setStatus(`${tool.label} → ${m.name}`);
    })
    .catch((e: Error) => s.setStatus(`${tool.label}: ${e.message}`));
}

/** Seed default values for a tool's inline parameter form. */
export function defaultParams(fields: ParamField[]): ParamValues {
  const out: ParamValues = {};
  for (const f of fields) out[f.key] = f.default;
  return out;
}
