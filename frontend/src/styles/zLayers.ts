// Single source of truth for the stacking-order ladder that spans both CSS
// and inline (TS-driven) z-indices. Layers that are pure CSS keep their
// value in theme-web/*.css (mirrored in the comment below); layers that a
// component computes at render time (tool windows, modal backdrops) import
// their numbers from here so the two sides can never drift apart, and so
// the relationship is assertable in jsdom (inline styles always resolve
// there, unlike rules loaded from an external stylesheet).
//
// Full ladder, low → high:
//
//   2 – 60      stage / inspector chrome        (02-05 theme-web/*.css)
//   30          menubar                         (01-shell-library.css)
//   40 / 41     menu dropdown / submenu          (01-shell-library.css)
//   200 – 290   floating tool/workshop windows   (TOOL_WINDOW_BASE, this file)
//   300         modal dialog backdrop            (MODAL_BACKDROP, this file;
//               mirrored in 06-overlays-export.css's .fvd-overlay-backdrop)
//   400 / 401   context-menu backdrop / menu     (02-stage.css)
//   2000        hover tooltip                    (01-shell-library.css)
//
// Modal dialogs (Batch, Export, Preferences, ...) must always win over
// floating tool windows — a dialog is application-modal and nothing behind
// it should be reachable, let alone visually on top of it.

/** Base z-index for floating tool/workshop windows (ToolWindow.tsx). */
export const TOOL_WINDOW_BASE = 200;

/**
 * Tool stacking order (`ToolWindowState.z`) is a monotonically increasing
 * per-session counter bumped on every open/focus (see openTool/focusTool in
 * viewerState.ts) — it is never reset or compacted. Clamp its contribution
 * to a fixed span so a long session of refocusing tool windows can never
 * climb into the modal layer above it. There are only 14 ToolKinds, so this
 * span is far larger than any real relative-order distinction ever needed.
 */
export const TOOL_WINDOW_SPAN = 90;

/** Highest possible tool-window z-index; MODAL_BACKDROP must exceed this. */
export const TOOL_WINDOW_MAX = TOOL_WINDOW_BASE + TOOL_WINDOW_SPAN;

/** z-index for the modal overlay backdrop (ModalDialog.tsx and friends). */
export const MODAL_BACKDROP = 300;

/** Resolve a tool window's rendered z-index from its store-tracked `z`. */
export function toolWindowZIndex(z: number): number {
  const clamped = Math.min(Math.max(z, 0), TOOL_WINDOW_SPAN);
  return TOOL_WINDOW_BASE + clamped;
}
