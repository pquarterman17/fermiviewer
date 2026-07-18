// ⌘K fuzzy command palette (handoff §4/§9): every action, grouped, with
// shortcut hints. Actions are supplied by App (they close over StageHandle).

import { useEffect, useMemo, useRef, useState } from "react";

import { fuzzy } from "../../lib/fuzzy";
import { mergeCommands, useCommands, type Action } from "../../store/commands";
import { useViewer } from "../../store/viewer";

export type { Action };

export default function CommandPalette({ actions }: { actions: Action[] }) {
  const open = useViewer((s) => s.cmdk);
  const setCmdk = useViewer((s) => s.setCmdk);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  // menu commands published by the MenuBar — snapshot them when the palette
  // opens (non-reactive: subscribing here would re-render on every MenuBar
  // render). The closures are fresh because the MenuBar republishes each render.
  const [menuCmds, setMenuCmds] = useState<Action[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    setQuery("");
    setCursor(0);
    setMenuCmds(useCommands.getState().menuCommands);
    // Focus after mount and restore the invoking control when dismissed.
    requestAnimationFrame(() => inputRef.current?.focus());
    return () => previousFocus?.focus();
  }, [open]);

  const allActions = useMemo(
    () => mergeCommands(actions, menuCmds),
    [actions, menuCmds],
  );

  const matches = useMemo(() => {
    const scored = allActions
      .map((a) => ({ a, m: fuzzy(query, a.label) }))
      .filter((x): x is { a: Action; m: NonNullable<typeof x.m> } => !!x.m)
      .sort((x, y) => y.m.score - x.m.score);
    return scored;
  }, [allActions, query]);

  useEffect(() => {
    setCursor(0);
  }, [query]);

  if (!open) return null;

  const run = (a: Action) => {
    setCmdk(false);
    a.run();
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Tab") {
      e.preventDefault();
      inputRef.current?.focus();
    } else if (e.key === "Escape") {
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
  const listId = "fvd-command-list";
  const optionId = (id: string) =>
    `fvd-command-${id.replace(/[^a-z0-9_-]/gi, "-")}`;
  const activeDescendant = matches[cursor]
    ? optionId(matches[cursor].a.id)
    : undefined;

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={() => setCmdk(false)}>
      <div
        className="fvd-glass fvd-cmdk"
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <input
          ref={inputRef}
          className="fvd-cmdk-input"
          role="combobox"
          aria-expanded="true"
          aria-autocomplete="list"
          aria-controls={listId}
          aria-activedescendant={activeDescendant}
          placeholder="Type a command…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={onKey}
        />
        <div className="fvd-cmdk-list" id={listId} role="listbox">
          {matches.length === 0 && (
            <div className="fvd-cmdk-empty">No matching commands</div>
          )}
          {matches.map(({ a, m }, i) => {
            const header =
              a.group !== lastGroup ? (
                <div className="fvd-cmdk-group" role="presentation">
                  {a.group}
                </div>
              ) : null;
            lastGroup = a.group;
            return (
              <div key={a.id} role="presentation">
                {header}
                <div
                  id={optionId(a.id)}
                  className={`fvd-cmdk-item${i === cursor ? " active" : ""}`}
                  role="option"
                  aria-selected={i === cursor}
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
