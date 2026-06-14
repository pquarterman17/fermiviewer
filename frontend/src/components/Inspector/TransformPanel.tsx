// GUI v2 phase 4 — Tools card: the in-panel home for image filters /
// transforms (formerly the Image-menu filter list). Searchable, grouped
// command list reusing the .fvd-cmd-* styling; click a parameterless tool
// to run it immediately, or expand a parameterised one and Apply inline.

import { Fragment, useState } from "react";

import { applyFilter } from "../../lib/api";
import { fuzzy } from "../../lib/fuzzy";
import { coerceParams, type ParamValues } from "../../lib/params";
import { applyGeometry, cropToRoi, type GeometryKind } from "../../lib/stageOps";
import {
  TRANSFORM_GROUPS,
  TRANSFORM_TOOLS,
  type TransformTool,
} from "../../lib/transformTools";
import { useViewer } from "../../store/viewer";
import { ParamFieldRow } from "../overlays/ParamFields";
import Card from "./Card";

/** Run a tool against the active image. Parameterless geometry/crop go
 *  straight through their stageOps helpers (undoable, status-reporting);
 *  parameterised filters POST /filter and ingest the derived image. */
function runTransform(tool: TransformTool, params: ParamValues): void {
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

export default function TransformPanel() {
  const activeId = useViewer((s) => s.activeId);
  const [query, setQuery] = useState("");
  const [openKind, setOpenKind] = useState<string | null>(null);
  const [values, setValues] = useState<ParamValues>({});

  if (!activeId) return null;

  const q = query.trim();
  const visible = q
    ? TRANSFORM_TOOLS.filter((t) => fuzzy(q, t.label) !== null)
    : TRANSFORM_TOOLS;

  const onToolClick = (tool: TransformTool) => {
    if (!tool.fields || tool.fields.length === 0) {
      runTransform(tool, {});
      setOpenKind(null);
      return;
    }
    if (openKind === tool.kind) {
      setOpenKind(null);
      return;
    }
    const init: ParamValues = {};
    for (const f of tool.fields) init[f.key] = f.default;
    setValues(init);
    setOpenKind(tool.kind);
  };

  const apply = (tool: TransformTool) => {
    runTransform(tool, coerceParams(values, tool.fields ?? []));
    setOpenKind(null);
  };

  return (
    <Card title="Tools" defaultOpen={false}>
      <div className="fvd-cmd-search">
        <span className="ico">⌕</span>
        <input
          value={query}
          placeholder="Filter image tools…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="fvd-tool-list">
        {TRANSFORM_GROUPS.map((group) => {
          const tools = visible.filter((t) => t.group === group);
          if (tools.length === 0) return null;
          return (
            <Fragment key={group}>
              <div className="fvd-cmd-group">
                <span>{group}</span>
                <span className="count">{tools.length}</span>
              </div>
              {tools.map((t) => {
                const expandable = !!t.fields && t.fields.length > 0;
                const open = openKind === t.kind;
                return (
                  <Fragment key={t.kind}>
                    <button
                      className={`fvd-cmd-row${open ? " active" : ""}`}
                      onClick={() => onToolClick(t)}
                    >
                      <span className="glyph">{t.glyph}</span>
                      <span className="label">{t.label}</span>
                      {expandable && (
                        <span className="chev">{open ? "▾" : "▸"}</span>
                      )}
                    </button>
                    {open && t.fields && (
                      <div className="fvd-tool-form">
                        {t.fields.map((f, i) => (
                          <ParamFieldRow
                            key={f.key}
                            field={f}
                            value={values[f.key]}
                            autoFocus={i === 0}
                            onChange={(v) =>
                              setValues((cur) => ({ ...cur, [f.key]: v }))
                            }
                          />
                        ))}
                        <div className="fvd-btn-row">
                          <button
                            className="fvd-btn"
                            onClick={() => setOpenKind(null)}
                          >
                            Cancel
                          </button>
                          <button
                            className="fvd-btn primary"
                            onClick={() => apply(t)}
                          >
                            Apply
                          </button>
                        </div>
                      </div>
                    )}
                  </Fragment>
                );
              })}
            </Fragment>
          );
        })}
        {visible.length === 0 && (
          <div className="fvd-cmd-empty">No tools match “{q}”.</div>
        )}
      </div>
    </Card>
  );
}
