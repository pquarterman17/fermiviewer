// GUI v2 — unified "Tools" browser (the mock's single PROCESSING panel
// with category pills). A/B alternative to the separate Measure + Tools
// cards: one searchable, pill-filtered, grouped command list combining
// the capture/measure tools and the filter/transform tools.

import { Fragment, useState } from "react";

import { fuzzy } from "../../lib/fuzzy";
import { MEASURE_GROUPS, MEASURE_TOOLS } from "../../lib/measureTools";
import { coerceParams, type ParamValues } from "../../lib/params";
import { defaultParams, runTransform } from "../../lib/transforms";
import {
  TRANSFORM_GROUPS,
  TRANSFORM_TOOLS,
  type TransformTool,
} from "../../lib/transformTools";
import { useViewer } from "../../store/viewer";
import { ParamFieldRow } from "../overlays/ParamFields";
import Card from "./Card";
import { useCollapsedGroups } from "./useCollapsedGroups";

const PILLS = ["All", "Measure", "Transform", "Filter"] as const;
type Pill = (typeof PILLS)[number];

// which transform groups each pill reveals ("Measure" shows none)
const TRANSFORM_PILL_GROUPS: Record<Pill, readonly string[]> = {
  All: TRANSFORM_GROUPS,
  Measure: [],
  Transform: ["Transform Image"],
  Filter: ["Filters", "Segment"],
};

export default function ToolsBrowser() {
  const activeId = useViewer((s) => s.activeId);
  const captureMode = useViewer((s) => s.captureMode);
  const setCaptureMode = useViewer((s) => s.setCaptureMode);
  const [pill, setPill] = useState<Pill>("All");
  const [query, setQuery] = useState("");
  const [openKind, setOpenKind] = useState<string | null>(null);
  const [values, setValues] = useState<ParamValues>({});
  const { collapsed, toggle } = useCollapsedGroups("tools-unified");

  if (!activeId) return null;

  const q = query.trim();
  const match = (label: string) => q === "" || fuzzy(q, label) !== null;
  const showMeasure = pill === "All" || pill === "Measure";
  const transformGroups = TRANSFORM_PILL_GROUPS[pill];

  const count =
    (showMeasure ? MEASURE_TOOLS.filter((t) => match(t.label)).length : 0) +
    TRANSFORM_TOOLS.filter(
      (t) => transformGroups.includes(t.group) && match(t.label),
    ).length;

  const onTransformClick = (tool: TransformTool) => {
    if (!tool.fields || tool.fields.length === 0) {
      runTransform(tool, {});
      setOpenKind(null);
      return;
    }
    if (openKind === tool.kind) {
      setOpenKind(null);
      return;
    }
    setValues(defaultParams(tool.fields));
    setOpenKind(tool.kind);
  };

  const apply = (tool: TransformTool) => {
    runTransform(tool, coerceParams(values, tool.fields ?? []));
    setOpenKind(null);
  };

  const header = (group: string, n: number, open: boolean) => (
    <button
      className="fvd-cmd-group"
      onClick={() => toggle(group)}
      title={open ? "Collapse group" : "Expand group"}
    >
      <span className="lbl">
        <span className="chev">{open ? "▾" : "▸"}</span>
        {group}
      </span>
      <span className="count">{n}</span>
    </button>
  );

  return (
    <Card title="Tools" count={count} defaultOpen={false}>
      <div className="fvd-cmd-search">
        <span className="ico">⌕</span>
        <input
          value={query}
          placeholder="Filter tools…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="fvd-pills">
        {PILLS.map((p) => (
          <button
            key={p}
            className={`fvd-pill${pill === p ? " active" : ""}`}
            onClick={() => setPill(p)}
          >
            {p}
          </button>
        ))}
      </div>
      <div className="fvd-tool-list">
        {showMeasure &&
          MEASURE_GROUPS.map((group) => {
            const tools = MEASURE_TOOLS.filter(
              (t) => t.group === group && match(t.label),
            );
            if (tools.length === 0) return null;
            const open = q !== "" || !collapsed.has(group);
            return (
              <Fragment key={group}>
                {header(group, tools.length, open)}
                {open &&
                  tools.map((t) => (
                    <button
                      key={t.kind}
                      className={`fvd-cmd-row${captureMode === t.kind ? " active" : ""}`}
                      onClick={() =>
                        setCaptureMode(captureMode === t.kind ? "none" : t.kind)
                      }
                    >
                      <span className="glyph">{t.glyph}</span>
                      <span className="label">{t.label}</span>
                      {captureMode === t.kind && <span className="dot" />}
                    </button>
                  ))}
              </Fragment>
            );
          })}
        {transformGroups.map((group) => {
          const tools = TRANSFORM_TOOLS.filter(
            (t) => t.group === group && match(t.label),
          );
          if (tools.length === 0) return null;
          const open = q !== "" || !collapsed.has(group);
          return (
            <Fragment key={group}>
              {header(group, tools.length, open)}
              {open &&
                tools.map((t) => {
                  const expandable = !!t.fields && t.fields.length > 0;
                  const isOpen = openKind === t.kind;
                  return (
                    <Fragment key={t.kind}>
                      <button
                        className={`fvd-cmd-row${isOpen ? " active" : ""}`}
                        onClick={() => onTransformClick(t)}
                      >
                        <span className="glyph">{t.glyph}</span>
                        <span className="label">{t.label}</span>
                        {expandable && (
                          <span className="chev">{isOpen ? "▾" : "▸"}</span>
                        )}
                      </button>
                      {isOpen && t.fields && (
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
        {count === 0 && (
          <div className="fvd-cmd-empty">No tools match “{q}”.</div>
        )}
      </div>
    </Card>
  );
}
