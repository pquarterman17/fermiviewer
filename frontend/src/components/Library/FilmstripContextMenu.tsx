// Right-click menu for a filmstrip card: show in stage, compare selected,
// rename, close — with roving keyboard focus (ARIA menu pattern).
//
// Extracted verbatim from Filmstrip.tsx.

import { useEffect, useRef } from "react";

/** Where the context menu was opened, and which card it's acting on. */
export interface FilmstripCtxTarget {
  x: number;
  y: number;
  id: string;
  returnFocus: HTMLDivElement | null;
}

export default function FilmstripContextMenu({
  at,
  canCompare,
  onShow,
  onCompare,
  onRename,
  onClose,
  dismiss,
}: {
  at: FilmstripCtxTarget;
  canCompare: boolean;
  onShow: () => void;
  onCompare: () => void;
  onRename: () => void;
  onClose: () => void;
  dismiss: (restoreFocus?: boolean) => void;
}) {
  const refs = useRef<Array<HTMLButtonElement | null>>([]);
  const liveItems = () =>
    refs.current.filter((node): node is HTMLButtonElement => node != null);

  useEffect(() => {
    requestAnimationFrame(() => liveItems()[0]?.focus());
  }, []);

  const focusItem = (index: number) => {
    const items = liveItems();
    if (items.length === 0) return;
    items[(index + items.length) % items.length]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    const items = liveItems();
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (e.key === "ArrowDown") focusItem(index + 1);
    else if (e.key === "ArrowUp") focusItem(index - 1);
    else if (e.key === "Home") focusItem(0);
    else if (e.key === "End") focusItem(items.length - 1);
    else if (e.key === "Escape") dismiss(true);
    else if (e.key === "Tab") {
      // APG: Tab closes the menu and continues the tab sequence. Without this
      // focus walked out to the page while the menu stayed open on screen.
      dismiss(false);
      return;
    } else return;
    e.preventDefault();
    e.stopPropagation();
  };

  const items = [
    { label: "Show in stage", run: onShow },
    { label: "Compare selected", run: onCompare, disabled: !canCompare },
    { label: "Rename…  F2", run: onRename },
    { label: "Close", run: onClose, separator: true },
  ];
  let focusIndex = 0;

  return (
    <div
      className="fvd-menu-dropdown fvd-film-ctx"
      style={{ left: at.x, top: at.y }}
      onMouseDown={(e) => e.stopPropagation()}
      onKeyDown={onKeyDown}
      role="menu"
      aria-label="Image actions"
    >
      {items.map((item) => {
        const index = item.disabled ? -1 : focusIndex++;
        return (
          <div key={item.label} role="presentation">
            {item.separator && <div className="fvd-menu-sep" role="separator" />}
            <button
              ref={(node) => {
                if (index >= 0) refs.current[index] = node;
              }}
              className="fvd-menu-entry"
              role="menuitem"
              // ARIA menus manage focus themselves: every item stays out of
              // the tab sequence and exactly one is focused programmatically.
              tabIndex={-1}
              disabled={item.disabled}
              onClick={() => {
                dismiss(true);
                item.run();
              }}
            >
              <span>{item.label}</span>
            </button>
          </div>
        );
      })}
    </div>
  );
}
