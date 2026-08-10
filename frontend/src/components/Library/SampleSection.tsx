// One collapsible filmstrip section — a sample, a project (which nests its
// samples), or the synthetic "Ungrouped" bucket (W4 #22).
//
// This is not a separate view the user switches to: Filmstrip renders these
// only once the project HAS sample groups, and falls back to the bare flat
// card list when it has none. Same panel, grown.

import { entryKey, type SampleNode } from "../../lib/sampleTree";
import Icon from "../icons/Icon";
import FilmCard, { type FilmCardCtx } from "./FilmCard";

/** Section chrome state + handlers, threaded down the tree unchanged. */
export interface SampleSectionCtx {
  collapsed: ReadonlySet<string>;
  toggle: (sectionId: string) => void;
  /** Section currently highlighted as a membership drop target. */
  dropSection: string | null;
  sectionDragOver: (sectionId: string, into: string | null) => void;
  sectionDragLeave: (sectionId: string) => void;
  sectionDrop: (into: string | null) => void;
}

export default function SampleSection({
  sectionId,
  name,
  groupId,
  depth,
  ids,
  subsections,
  ctx,
  sec,
}: {
  /** Collapse key. Equals `groupId` for a real group. */
  sectionId: string;
  name: string;
  /** Membership target for a card dropped here; null = belongs to no sample. */
  groupId: string | null;
  depth: number;
  ids: string[];
  subsections: SampleNode[];
  ctx: FilmCardCtx;
  sec: SampleSectionCtx;
}) {
  const isCollapsed = sec.collapsed.has(sectionId);
  const cls = [
    "fvd-sample-section",
    depth > 0 ? "nested" : "",
    sec.dropSection === sectionId ? "drop-into" : "",
  ]
    .filter(Boolean)
    .join(" ");
  // a section holds every image below it, so a project's count includes its
  // samples' — that is the number the user is grouping by
  const total = ids.length + countIds(subsections);
  return (
    <div
      className={cls}
      role="group"
      aria-label={name}
      // drop anywhere in the section (its header, its gaps, a collapsed
      // section's bar) to move the dragged image into it — otherwise an
      // empty or collapsed sample would be unreachable as a target
      onDragOver={(e) => {
        e.preventDefault();
        sec.sectionDragOver(sectionId, groupId);
      }}
      onDragLeave={() => sec.sectionDragLeave(sectionId)}
      onDrop={(e) => {
        e.preventDefault();
        sec.sectionDrop(groupId);
      }}
    >
      <button
        className="fvd-sample-head"
        aria-expanded={!isCollapsed}
        onClick={() => sec.toggle(sectionId)}
        title={isCollapsed ? `Expand ${name}` : `Collapse ${name}`}
      >
        <Icon name={isCollapsed ? "chevron-right" : "chevron-down"} />
        <span className="fvd-sample-name">{name}</span>
        <span className="fvd-sample-count">{total}</span>
      </button>
      {!isCollapsed && (
        <div className="fvd-sample-body">
          {ids.map((id) => (
            <FilmCard
              key={entryKey({ id, groupId })}
              id={id}
              groupId={groupId}
              ctx={ctx}
            />
          ))}
          {subsections.map((child) => (
            <SampleSection
              key={child.group.id}
              sectionId={child.group.id}
              name={child.group.name}
              groupId={child.group.id}
              depth={child.depth}
              ids={child.ids}
              subsections={child.children}
              ctx={ctx}
              sec={sec}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function countIds(nodes: SampleNode[]): number {
  return nodes.reduce((n, c) => n + c.ids.length + countIds(c.children), 0);
}
