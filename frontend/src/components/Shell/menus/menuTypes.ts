// Shared types + the narrow useViewer selector for MenuBar's per-group menu
// builder modules (repo-health #33 decomposition of MenuBar.tsx). MenuBar
// itself owns the component, its local state/effects and every helper
// closure; these builder modules only assemble the menu entry arrays.

import type { ImageMeta } from "../../../lib/api";
import type { ParamField } from "../../../lib/params";
import type { Measure, ViewerState } from "../../../store/viewer";
import type { MenuEntry as Entry } from "../DesktopMenus";

export type { Entry };

export const num = (
  key: string,
  label: string,
  dflt: number,
  hint?: string,
): ParamField => ({ key, label, type: "number", default: dflt, hint });

// narrow selector: only the fields the menu STRUCTURE reads (labels,
// disabled state, submenu content) + the stable action refs every
// `store.<action>()` call site below needs. A whole-store `useViewer()`
// subscription re-rendered this 1,600-line component on every store write
// (e.g. once per pointermove while panning/zooming, which only touch
// views/display/tools — fields never read here).
export function menuStoreSelector(s: ViewerState) {
  return {
    activeId: s.activeId,
    selected: s.selected,
    order: s.order,
    images: s.images,
    measures: s.measures,
    undoStack: s.undoStack,
    redoStack: s.redoStack,
    minimap: s.minimap,
    scaleBarVisible: s.scaleBarVisible,
    colorbar: s.colorbar,
    theme: s.theme,
    leftCol: s.leftCol,
    rightCol: s.rightCol,
    // actions are stable references — including them here never triggers
    // an extra render, and keeps every call site below unchanged
    setStatus: s.setStatus,
    openFiles: s.openFiles,
    openPaths: s.openPaths,
    closeImage: s.closeImage,
    saveWorkspace: s.saveWorkspace,
    loadWorkspace: s.loadWorkspace,
    undo: s.undo,
    redo: s.redo,
    clearMeasures: s.clearMeasures,
    setPrefsOpen: s.setPrefsOpen,
    toggleMinimap: s.toggleMinimap,
    toggleScaleBar: s.toggleScaleBar,
    setGalleryOpen: s.setGalleryOpen,
    startSideBySide: s.startSideBySide,
    toggleColorbar: s.toggleColorbar,
    toggleTheme: s.toggleTheme,
    toggleLeft: s.toggleLeft,
    toggleRight: s.toggleRight,
    setExportOpen: s.setExportOpen,
    setCaptureMode: s.setCaptureMode,
    removeMeasure: s.removeMeasure,
    ingest: s.ingest,
    ingestDerived: s.ingestDerived,
    setCmdk: s.setCmdk,
    setShorts: s.setShorts,
    setBatchOpen: s.setBatchOpen,
    setCalibOpen: s.setCalibOpen,
    setMetaOpen: s.setMetaOpen,
    openTool: s.openTool,
  };
}

export type MenuStore = ReturnType<typeof menuStoreSelector>;

// Everything a group builder needs beyond the narrow store slice: props
// threaded down from MenuBar's caller, and the helper closures that stay in
// MenuBar (they close over component-local state like `fileRef`/`macroRec`
// or module-level singletons like `useResults`/`useStageInfo`).
export interface MenuCtx {
  store: MenuStore;
  onFit: () => void;
  onActualSize: () => void;
  openFiles: () => void;
  macroRec: boolean;
  setMacroRec: (v: boolean) => void;
  derived: (label: string, run: (id: string) => Promise<ImageMeta[]>) => void;
  lastProfileMeasure: () => Measure | undefined;
  runBatchProfile: () => Promise<void>;
  runBatchCrop: () => Promise<void>;
  runBatch: () => Promise<void>;
  radialDock: (azimuthal: boolean) => void;
  calibrateFromMeasurement: () => void;
}
