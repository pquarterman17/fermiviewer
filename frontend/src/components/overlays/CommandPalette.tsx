// ⌘K fuzzy command palette (handoff §4/§9): every action, grouped, with
// shortcut hints. Actions are supplied by App (they close over StageHandle).

import { useEffect, useMemo, useRef, useState } from "react";

import { fuzzy } from "../../lib/fuzzy";
import { useViewer } from "../../store/viewer";

export interface Action {
  id: string;
  group: string;
  label: string;
  shortcut?: string;
  run: () => void;
}

export default function CommandPalette({ actions }: { actions: Action[] }) {
  const open = useViewer((s) => s.cmdk);
  const setCmdk = useViewer((s) => s.setCmdk);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // focus after mount
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  const matches = useMemo(() => {
    const scored = actions
      .map((a) => ({ a, m: fuzzy(query, a.label) }))
      .filter((x): x is { a: Action; m: NonNullable<typeof x.m> } => !!x.m)
      .sort((x, y) => y.m.score - x.m.score);
    return scored;
  }, [actions, query]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  if (!open) return null;

  const run = (a: Action) => {
    setCmdk(false);
    a.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setCmdk(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(matches.length - 1, c + 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(0, c - 1));
    } else if (e.key === "Enter" && matches[cursor]) {
      run(matches[cursor].a);
    }
    e.stopPropagation();
  };

  // group in match order, preserving rank
  let lastGroup = "";

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setCmdk(false)}>
      <div
        className="fvd-glass fvd-cmdk"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="fvd-cmdk-input"
          placeholder="Type a command…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="fvd-cmdk-list">
          {matches.length === 0 && (
            <div className="fvd-cmdk-empty">No matching commands</div>
          )}
          {matches.map(({ a, m }, i) => {
            const header =
              a.group !== lastGroup ? (
                <div className="fvd-cmdk-group">{a.group}</div>
              ) : null;
            lastGroup = a.group;
            return (
              <div key={a.id}>
                {header}
                <div
                  className={`fvd-cmdk-item${i === cursor ? " active" : ""}`}
                  onMouseEnter={() => setCursor(i)}
                  onMouseDown={() => run(a)}
                >
                  <span>{highlight(a.label, m.hits)}</span>
                  {a.shortcut && (
                    <span className="fvd-shortcut">{a.shortcut}</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function highlight(label: string, hits: number[]): React.ReactNode {
  if (hits.length === 0) return label;
  const set = new Set(hits);
  return label.split("").map((ch, i) =>
    set.has(i) ? (
      <mark key={i} className="fvd-cmdk-hit">
        {ch}
      </mark>
    ) : (
      ch
    ),
  );
}
