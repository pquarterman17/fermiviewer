import { lazy, type ReactNode } from "react";
import { useShallow } from "zustand/react/shallow";

import { useParamDialog } from "../../store/params";
import { useViewer, type ViewerState } from "../../store/viewer";
import ChunkBoundary from "../ChunkBoundary";

const BatchDialog = lazy(() => import("./BatchDialog"));
const CalibrationManager = lazy(() => import("./CalibrationManager"));
const ExportDialog = lazy(() => import("./ExportDialog"));
const FolderOpenDialog = lazy(() => import("./FolderOpenDialog"));
const GalleryGrid = lazy(() => import("./GalleryGrid"));
const MetadataDialog = lazy(() => import("./MetadataDialog"));
const ParamDialog = lazy(() => import("./ParamDialog"));
const PrefsWindow = lazy(() => import("./PrefsWindow"));
const ShortcutsOverlay = lazy(() => import("./ShortcutsOverlay"));

/** Mount modal code only after its corresponding open state is requested. */
export default function LazyOverlays() {
  const open = useViewer(
    useShallow((state) => ({
      batch: state.batchOpen,
      calibrations: state.calibOpen,
      export: state.exportOpen,
      folder: state.folderOpen,
      gallery: state.galleryOpen,
      metadata: state.metaOpen,
      preferences: state.prefsOpen,
      shortcuts: state.shorts,
    })),
  );
  const params = useParamDialog((state) => state.queue.length > 0);

  // One boundary PER overlay, never a shared one. Overlays stack (BatchDialog
  // awaits askParams -> ParamDialog), and a shared boundary re-suspends on the
  // second chunk: React hides the already-committed dialog and tears down its
  // effects, so the open dialog blanks and its focus state is lost. Each
  // boundary mounts with its overlay, so a failed load resets on close.
  return (
    <>
      {open.batch && <Boundary label="Batch" flag="batchOpen"><BatchDialog /></Boundary>}
      {open.calibrations && (
        <Boundary label="Calibrations" flag="calibOpen"><CalibrationManager /></Boundary>
      )}
      {open.export && <Boundary label="Export" flag="exportOpen"><ExportDialog /></Boundary>}
      {open.folder && <Boundary label="Open Folder" flag="folderOpen"><FolderOpenDialog /></Boundary>}
      {open.gallery && <Boundary label="Gallery" flag="galleryOpen"><GalleryGrid /></Boundary>}
      {open.metadata && <Boundary label="Metadata" flag="metaOpen"><MetadataDialog /></Boundary>}
      {params && (
        <ChunkBoundary
          label="Parameters"
          className="fvd-glass floating"
          onDismiss={() => useParamDialog.getState().close()}
        >
          <ParamDialog />
        </ChunkBoundary>
      )}
      {open.preferences && <Boundary label="Preferences" flag="prefsOpen"><PrefsWindow /></Boundary>}
      {open.shortcuts && <Boundary label="Shortcuts" flag="shorts"><ShortcutsOverlay /></Boundary>}
    </>
  );
}

type OverlayFlag = {
  [K in keyof ViewerState]: ViewerState[K] extends boolean ? K : never;
}[keyof ViewerState];

/** A failed overlay has no dialog of its own to close, so the notice floats
 *  and its Close clears the open flag that requested it. */
function Boundary({
  label,
  flag,
  children,
}: {
  label: string;
  flag: OverlayFlag;
  children: ReactNode;
}) {
  return (
    <ChunkBoundary
      label={label}
      className="fvd-glass floating"
      onDismiss={() => useViewer.setState({ [flag]: false })}
    >
      {children}
    </ChunkBoundary>
  );
}
