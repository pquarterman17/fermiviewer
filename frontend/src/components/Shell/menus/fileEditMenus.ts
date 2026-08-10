// File + Edit menu builders, split out of MenuBar.tsx (repo-health #33).
// Entries moved verbatim; only `store`/helper references now come from ctx.
import { ANNOTATION_KINDS, MEASUREMENT_KINDS } from "../../../lib/measureKinds";
import {
  exportBatch,
  exportFigure,
  exportGif,
  renameImage,
} from "../../../lib/api";
import { copyActive } from "../../../lib/export";
import { askParams } from "../../../store/params";
import { undoLabel, useViewer } from "../../../store/viewer";
import type { Entry, MenuCtx } from "./menuTypes";
import { num } from "./menuTypes";

function recentPaths(): string[] {
  try {
    // The store persists up to 8 (viewer.ts fv_recent); the old flat listing
    // showed only 5 to keep the File menu short — the submenu removes that
    // constraint, so show everything persisted.
    return (
      JSON.parse(localStorage.getItem("fv_recent") ?? "[]") as string[]
    ).slice(0, 8);
  } catch {
    return [];
  }
}

/** "Recent Images" submenu entry: filenames only (the submenu heading says
 *  what they are); disabled placeholder — no submenu key, so it can't
 *  expand into an empty box — when nothing has been opened yet. */
export function recentImagesEntry(store: MenuCtx["store"]): Entry {
  const recents = recentPaths();
  if (!recents.length) return { label: "Recent Images", disabled: true };
  return {
    label: "Recent Images",
    submenu: recents.map((p) => ({
      label: p.split(/[\\/]/).pop() ?? p,
      action: () =>
        store.openPaths([p]).catch((e: Error) => store.setStatus(e.message)),
    })),
  };
}

/** The project commands (PROJECT_WORKFLOW_PLAN #32–#35, format ADR 0002).
 *
 *  Save Project and Export Project Bundle are deliberately TWO entries rather
 *  than one dialog with a mode picker: the everyday save is megabytes and
 *  references the source folders, the bundle is hundreds of MB and needs
 *  none — a difference the user must choose knowingly, not discover later
 *  when a project opens with no data on another machine.
 *
 *  Locate Data Folder… stays in the menu (not only in the library's
 *  unavailable block) because it is repeatable: different samples may have
 *  moved to different folders, so it is invoked once per folder, and it must
 *  be reachable without hunting for a card. */
function projectEntries(store: MenuCtx["store"]): Entry[] {
  const missing = Object.keys(store.unavailable).length;
  const nothingToSave = store.order.length === 0 && missing === 0;
  return [
    { kind: "sep" },
    {
      label: "Save Project…",
      disabled: nothingToSave,
      action: () => {
        const p = window.prompt("Save project to path (.fvp):");
        if (p) {
          store
            .saveProject(p, "light")
            .catch((e: Error) => store.setStatus(e.message));
        }
      },
    },
    {
      label: "Export Project Bundle…",
      disabled: nothingToSave,
      action: () => {
        const p = window.prompt(
          "Export a self-contained project bundle to path (.fvp) — " +
            "embeds every image, so it needs no source folders:",
        );
        if (p) {
          store
            .saveProject(p, "bundle")
            .catch((e: Error) => store.setStatus(e.message));
        }
      },
    },
    {
      label: "Open Project…",
      action: () => {
        const p = window.prompt("Open project from path (.fvp):");
        if (p) {
          store
            .openProject(p)
            .catch((e: Error) => store.setStatus(e.message));
        }
      },
    },
    {
      label: missing
        ? `Locate Data Folder… (${missing} unavailable)`
        : "Locate Data Folder…",
      disabled: missing === 0,
      action: () => {
        const root = window.prompt(
          "Folder the missing images are in now (every image under it is " +
            "re-linked; repeat for samples that moved elsewhere):",
        );
        if (root) {
          store
            .locateData(root)
            .catch((e: Error) => store.setStatus(e.message));
        }
      },
    },
    { kind: "sep" },
  ];
}

export function buildFileMenu(ctx: MenuCtx): Entry[] {
  const { store, openFiles } = ctx;
  return [
    { label: "Open…", shortcut: "⌘O", action: openFiles },
    recentImagesEntry(store),
    {
      label: `Batch Export… (${store.selected.length})`,
      disabled: store.selected.length < 2,
      action: () => {
        void (async () => {
          const v = await askParams("Batch Export (ZIP)", [
            {
              key: "format",
              label: "Format",
              type: "select",
              default: "png",
              options: ["png", "jpeg", "tiff16"],
            },
            {
              key: "scale",
              label: "Resolution",
              type: "select",
              default: "1",
              options: ["1", "2", "3", "4"],
            },
          ]);
          if (!v) return;
          exportBatch(store.selected, {
            format: v["format"] as string,
            scale: Number(v["scale"]),
          })
            .then((blob) => {
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "export.zip";
              a.click();
              URL.revokeObjectURL(url);
              store.setStatus(
                `batch exported ${store.selected.length} images`,
              );
            })
            .catch((e: Error) => store.setStatus(`batch: ${e.message}`));
        })();
      },
    },
    {
      label: `Export Figure Panel… (${store.selected.length})`,
      disabled: store.selected.length < 2,
      action: () => {
        void (async () => {
          const v = await askParams("Figure panel (labeled grid)", [
            num("cols", "Columns (0 = auto)", 0),
            num("gap", "Gap (px)", 4),
            {
              key: "scale",
              label: "Resolution",
              type: "select",
              default: "1",
              options: ["1", "2", "3", "4"],
            },
          ]);
          if (!v) return;
          exportFigure(store.selected, {
            cols: v["cols"] as number,
            gap: v["gap"] as number,
            scale: Number(v["scale"]),
          })
            .then((blob) => {
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = "figure.png";
              a.click();
              URL.revokeObjectURL(url);
              store.setStatus(
                `figure panel: ${store.selected.length} panels`,
              );
            })
            .catch((e: Error) => store.setStatus(`figure: ${e.message}`));
        })();
      },
    },
    {
      label: `Batch Rename… (${store.selected.length})`,
      disabled: store.selected.length < 2,
      action: () => {
        void (async () => {
          const v = await askParams("Batch Rename", [
            {
              key: "prefix",
              label: "Prefix (gets _001, _002…)",
              type: "text",
              default: "frame",
            },
          ]);
          if (!v || !v["prefix"]) return;
          const prefix = v["prefix"] as string;
          let n = 0;
          for (const id of store.selected) {
            n++;
            try {
              const m = await renameImage(
                id,
                `${prefix}_${String(n).padStart(3, "0")}`,
              );
              useViewer.setState((s) => ({
                images: { ...s.images, [m.id]: m },
              }));
            } catch {
              /* keep renaming the rest */
            }
          }
          store.setStatus(`renamed ${n} images`);
        })();
      },
    },
    ...projectEntries(store),
    {
      label: "Copy to Clipboard",
      disabled: !store.activeId,
      action: () => {
        // shared with the radial "Copy": bakes scale bar + measurements
        // by default so both copy paths behave identically
        copyActive()
          .then(() =>
            store.setStatus("copied to clipboard (scale bar + measurements)"),
          )
          .catch((e: Error) => store.setStatus(`clipboard: ${e.message}`));
      },
    },
    {
      label: "Copy as Vector (SVG)",
      disabled: !store.activeId,
      action: () => {
        // true-vector SVG where the paste target supports it (crisp text at
        // any scale); transparently falls back to PNG (e.g. in Firefox)
        copyActive({ format: "png", scale: 1, vector: true })
          .then(() => store.setStatus("copied to clipboard (vector SVG)"))
          .catch((e: Error) => store.setStatus(`clipboard: ${e.message}`));
      },
    },
    {
      label: `Export GIF… (${store.selected.length} frames)`,
      disabled: store.selected.length < 2,
      action: () => {
        void (async () => {
          const v = await askParams("Export GIF", [
            num("fps", "Frames per second", 4),
            {
              key: "scale",
              label: "Resolution",
              type: "select",
              default: "1",
              options: ["1", "2", "3", "4"],
            },
            {
              key: "cmap",
              label: "Colormap",
              type: "select",
              default: "gray",
              options: ["gray", "viridis", "inferno", "magma", "plasma"],
            },
          ]);
          if (!v) return;
          exportGif(store.selected, {
            fps: v["fps"] as number,
            scale: Number(v["scale"]),
            cmap: v["cmap"] as string,
          })
            .then(({ blob, filename }) => {
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url;
              a.download = filename;
              a.click();
              URL.revokeObjectURL(url);
              store.setStatus(`exported ${filename}`);
            })
            .catch((e: Error) => store.setStatus(`gif: ${e.message}`));
        })();
      },
    },
    {
      label: "Export…",
      shortcut: "⌘E",
      disabled: !store.activeId,
      action: () => store.setExportOpen(true),
    },
    {
      label: "Close Image",
      shortcut: "⌘W",
      disabled: !store.activeId,
      action: () => {
        if (store.activeId) void store.closeImage(store.activeId);
      },
    },
  ];
}

export function buildEditMenu(ctx: MenuCtx): Entry[] {
  const { store } = ctx;
  return [
    {
      label:
        store.undoStack.length > 0
          ? `Undo ${undoLabel(store.undoStack[store.undoStack.length - 1])}`
          : "Undo",
      shortcut: "⌘Z",
      disabled: store.undoStack.length === 0,
      action: () => {
        const e = store.undo();
        if (e) store.setStatus(`undo: ${undoLabel(e)}`);
      },
    },
    {
      label:
        store.redoStack.length > 0
          ? `Redo ${undoLabel(store.redoStack[store.redoStack.length - 1])}`
          : "Redo",
      shortcut: "⇧⌘Z",
      disabled: store.redoStack.length === 0,
      action: () => {
        const e = store.redo();
        if (e) store.setStatus(`redo: ${undoLabel(e)}`);
      },
    },
    {
      label: "Clear Measurements",
      disabled:
        !store.activeId ||
        (store.measures[store.activeId ?? ""] ?? []).length === 0,
      action: () => {
        if (store.activeId) {
          store.clearMeasures(store.activeId, [...MEASUREMENT_KINDS]);
          store.setStatus("measurements cleared (undoable)");
        }
      },
    },
    {
      label: "Clear Annotations",
      disabled:
        !store.activeId ||
        (store.measures[store.activeId ?? ""] ?? []).length === 0,
      action: () => {
        if (store.activeId) {
          store.clearMeasures(store.activeId, [...ANNOTATION_KINDS]);
          store.setStatus("annotations cleared (undoable)");
        }
      },
    },
    {
      label: "Clear All Overlays",
      disabled:
        !store.activeId ||
        (store.measures[store.activeId ?? ""] ?? []).length === 0,
      action: () => {
        if (store.activeId) {
          store.clearMeasures(store.activeId, null);
          store.setStatus("overlays cleared (undoable)");
        }
      },
    },
    { kind: "sep" },
    {
      label: "Preferences…",
      shortcut: "⌘,",
      action: () => store.setPrefsOpen(true),
    },
  ];
}
