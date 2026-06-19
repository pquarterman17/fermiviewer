// Single source of truth for ⌘K palette commands. The MenuBar owns the full
// menu tree and publishes its flattened entries here on every render (so the
// closures stay bound to the current store snapshot — never stale). The
// CommandPalette reads them non-reactively when it opens and merges them with
// App's curated actions, so every menu command is searchable and the two can
// never drift apart. App must NOT subscribe to this store reactively — the
// MenuBar re-renders on App renders, so a reactive merge would loop.

import { create } from "zustand";

export interface Action {
  id: string;
  group: string;
  label: string;
  shortcut?: string;
  run: () => void;
}

interface CommandsState {
  menuCommands: Action[];
  setMenuCommands: (cmds: Action[]) => void;
}

export const useCommands = create<CommandsState>((set) => ({
  menuCommands: [],
  setMenuCommands: (menuCommands) => set({ menuCommands }),
}));

/** Merge curated palette actions with the published menu commands. Menu
 *  commands whose label duplicates a curated one are dropped (curated wins —
 *  it has the nicer grouping + shortcut), so each command appears once. */
export function mergeCommands(curated: Action[], menu: Action[]): Action[] {
  const seen = new Set(curated.map((a) => a.label.toLowerCase()));
  const extra = menu.filter((a) => !seen.has(a.label.toLowerCase()));
  return [...curated, ...extra];
}
