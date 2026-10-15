// View + Window + Help menu builders, split out of MenuBar.tsx
// (repo-health #33). Entries moved verbatim; only `store`/prop references
// now come from ctx.
import { downloadBugReport } from "../../../lib/errlog";
import {
  addImagesToGroup,
  compareGroupsSideBySide,
  deleteAllGroups,
  deleteGroupPicked,
  groupImages,
  groupsContaining,
  removeImagesFromGroups,
  sideBySidePair,
} from "../../../lib/groupActions";
import { isSpmHeightImage } from "../../../lib/spm";
import type { Entry, MenuCtx } from "./menuTypes";

export function buildViewMenu(ctx: MenuCtx): Entry[] {
  const { store, onFit, onActualSize } = ctx;
  return [
    { label: "Fit", shortcut: "F", disabled: !store.activeId, action: onFit },
    {
      label: "Actual Size",
      shortcut: "1",
      disabled: !store.activeId,
      action: onActualSize,
    },
    {
      label: store.minimap ? "Hide Minimap" : "Show Minimap",
      action: store.toggleMinimap,
    },
    {
      label: store.scaleBarVisible ? "Hide Scale Bar" : "Show Scale Bar",
      disabled: !store.activeId,
      action: store.toggleScaleBar,
    },
    {
      label: "Image Gallery",
      shortcut: "V",
      disabled: store.order.length === 0,
      action: () => store.setGalleryOpen(true),
    },
    {
      label: "Side-by-side Compare",
      disabled: store.order.length === 0,
      action: store.startSideBySide,
    },
    {
      label: "Groups",
      submenu: [
        {
          label: `Group Selected (${store.selected.length})…`,
          disabled: store.selected.length === 0,
          action: () => void groupImages(store.selected),
        },
        {
          label: `Add Selected to Group (${store.selected.length})…`,
          disabled: store.selected.length === 0 || store.imageGroups.length === 0,
          action: () => void addImagesToGroup(store.selected),
        },
        {
          label: `Remove Selected from Groups (${store.selected.length})`,
          disabled:
            groupsContaining(store.imageGroups, store.selected).length === 0,
          action: () => removeImagesFromGroups(store.selected),
        },
        {
          label: "Compare Two Groups Side by Side",
          disabled:
            sideBySidePair(store.imageGroups, store.images, store.selected)
              .length < 2,
          action: compareGroupsSideBySide,
        },
        { kind: "sep" },
        {
          label: "Delete Group…",
          disabled: store.imageGroups.length === 0,
          action: () => void deleteGroupPicked(),
        },
        {
          label: "Delete All Groups…",
          disabled: store.imageGroups.length === 0,
          action: deleteAllGroups,
        },
      ],
    },
    {
      label: store.colorbar ? "Hide Colorbar" : "Show Colorbar",
      action: store.toggleColorbar,
    },
    {
      label: store.theme === "dark" ? "Light Theme" : "Dark Theme",
      shortcut: "⌘⇧L",
      action: store.toggleTheme,
    },
    {
      label: store.leftCol ? "Show Library" : "Hide Library",
      shortcut: "⌘[",
      action: store.toggleLeft,
    },
    {
      label: store.rightCol ? "Show Inspector" : "Hide Inspector",
      shortcut: "⌘]",
      action: store.toggleRight,
    },
  ];
}

export function buildWindowMenu(ctx: MenuCtx): Entry[] {
  const { store } = ctx;
  const activeMeta = store.activeId ? store.images[store.activeId] : undefined;
  const afmHeight = isSpmHeightImage(activeMeta);
  return [
    {
      label: "Analysis Workspaces",
      submenu: [
        {
          label: "Results & Methods",
          action: () => store.openTool("results"),
        },
        {
          label: "Elemental Analysis",
          action: () => store.openTool("eds"),
        },
        {
          label: "Diffraction",
          action: () => store.openTool("diffraction"),
        },
        {
          label: "Structure",
          action: () => store.openTool("structure"),
        },
        {
          label: "Cross-section Layers",
          action: () => store.openTool("layers"),
        },
        {
          label: afmHeight ? "AFM Surface Analysis" : "Surface Roughness",
          disabled: !store.activeId,
          action: () => store.openTool(afmHeight ? "afmsurface" : "roughness"),
        },
        {
          label: "4D-STEM Viewer",
          action: () => store.openTool("fourd"),
        },
      ],
    },
    {
      label: "Inspectors & Visualization",
      submenu: [
        {
          label: "FFT Mask Editor",
          action: () => store.openTool("fftmask"),
        },
        { label: "Pixel Inspector", action: () => store.openTool("pixels") },
        { label: "Color Overlay", action: () => store.openTool("overlay") },
        { label: "Surface Plot", action: () => store.openTool("surface") },
      ],
    },
  ];
}

export function buildHelpMenu(ctx: MenuCtx): Entry[] {
  const { store } = ctx;
  return [
    {
      label: "Keyboard Shortcuts",
      shortcut: "?",
      action: () => store.setShorts(true),
    },
    {
      label: "Report a Bug…",
      action: () => {
        downloadBugReport()
          .then(() =>
            store.setStatus(
              "bug report downloaded — attach it to your issue",
            ),
          )
          .catch((e: Error) => store.setStatus(`report: ${e.message}`));
      },
    },
    {
      // Manual fallback for the desktop auto-updater: opens the latest
      // GitHub Release (the runnable installer lives there). target=_blank
      // → new tab in the browser app, system browser in the Tauri shell;
      // the app window never navigates away.
      label: "Check for Updates…",
      action: () => {
        window.open(
          "https://github.com/pquarterman17/fermiviewer/releases/latest",
          "_blank",
          "noopener",
        );
        store.setStatus("opened the latest release page in your browser");
      },
    },
    {
      label: "Command Palette",
      shortcut: "⌘K",
      action: () => store.setCmdk(true),
    },
  ];
}
