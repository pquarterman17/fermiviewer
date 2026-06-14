// Per-group collapsed state for a command list (GUI v2 plan §3/§9 —
// "group headers carry a chevron + count for collapse"). Persisted under
// localStorage["fv_groups_<key>"]; groups default to expanded, so the
// stored set holds the COLLAPSED group names. Shared by MeasurePanel and
// TransformPanel.

import { useCallback, useState } from "react";

const PREFIX = "fv_groups_";

function load(key: string): Set<string> {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? new Set(parsed as string[]) : new Set();
  } catch {
    return new Set();
  }
}

function persist(key: string, set: Set<string>): void {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify([...set]));
  } catch {
    // storage quota / private mode — collapse just won't persist
  }
}

export function useCollapsedGroups(key: string): {
  collapsed: Set<string>;
  toggle: (group: string) => void;
} {
  const [collapsed, setCollapsed] = useState<Set<string>>(() => load(key));
  const toggle = useCallback(
    (group: string) => {
      setCollapsed((prev) => {
        const next = new Set(prev);
        if (next.has(group)) next.delete(group);
        else next.add(group);
        persist(key, next);
        return next;
      });
    },
    [key],
  );
  return { collapsed, toggle };
}
