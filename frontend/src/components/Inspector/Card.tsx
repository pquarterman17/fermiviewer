// Shared collapsible card — visually identical to the native
// <details class="fvd-card"> pattern already used in MeasurePanel.
// Collapsed state is persisted in localStorage under "fv_cards"
// (a keyed map from card title → boolean, true = open).
// Default: open (matching today's behaviour before this component).

import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";

const STORAGE_KEY = "fv_cards";

/** Load the persisted map once; never return a fresh object literal
 *  from inside a render path (Zustand black-screen rule applies here
 *  too — stale closures over fresh [] / {} cause loops). */
function loadMap(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (parsed !== null && typeof parsed === "object" && !Array.isArray(parsed)) {
      return parsed as Record<string, boolean>;
    }
    return {};
  } catch {
    return {};
  }
}

function persistMap(map: Record<string, boolean>): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(map));
  } catch {
    // storage quota or private-mode — silently skip
  }
}

interface CardProps {
  /** Card title shown in the summary/header. Also used as the
   *  localStorage key — must be unique within the inspector. */
  title: string;
  children: ReactNode;
  /** Override the default-open behaviour (default: true). */
  defaultOpen?: boolean;
  /** Optional count badge shown next to the title (e.g. item count). */
  count?: number;
}

/** Collapsible inspector card backed by a native <details> element so
 *  keyboard accessibility (Enter/Space on the summary) comes for free.
 *  The collapsed state is persisted in localStorage["fv_cards"]. */
export default function Card({
  title,
  children,
  defaultOpen = true,
  count,
}: CardProps) {
  // initialise from persisted state; fall back to defaultOpen
  const [open, setOpen] = useState<boolean>(() => {
    const map = loadMap();
    return title in map ? map[title] : defaultOpen;
  });

  // keep a ref so the toggle handler does not re-subscribe on every render
  const openRef = useRef(open);
  openRef.current = open;

  const toggle = useCallback(() => {
    const next = !openRef.current;
    setOpen(next);
    const map = loadMap();
    map[title] = next;
    persistMap(map);
  }, [title]);

  // Sync when title changes (e.g. dynamic cards) — read persisted state
  useEffect(() => {
    const map = loadMap();
    if (title in map) {
      setOpen(map[title]);
    }
  }, [title]);

  return (
    <details
      className="fvd-card"
      open={open}
      onToggle={(e) => {
        // <details> fires onToggle on open/close — keep React state in sync
        // when the browser handles the native toggle (e.g. keyboard or AT)
        const next = (e.currentTarget as HTMLDetailsElement).open;
        if (next !== openRef.current) {
          setOpen(next);
          const map = loadMap();
          map[title] = next;
          persistMap(map);
        }
      }}
    >
      <summary
        onClick={(e) => {
          // Prevent the default toggle so we control state ourselves;
          // this keeps React state and DOM open attribute in sync.
          e.preventDefault();
          toggle();
        }}
      >
        {title}
        {count != null && <span className="fvd-card-count">{count}</span>}
      </summary>
      {children}
    </details>
  );
}
