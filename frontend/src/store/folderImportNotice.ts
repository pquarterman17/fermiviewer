// Persistent folder-import outcome (PROJECT_WORKFLOW_PLAN.md item 5):
// standalone store, same shape as store/browseScale.ts — kept OUT of
// store/viewer.ts for the same reason (additive UI-only state has no
// business in the pinned session-shaped store).
//
// Both folder-import entry points (the dialog's Import button, item 2/3;
// dropping a folder onto the window, item 4) report through this ONE
// store via lib/folderImport.ts's `applyFolderImport`, so there is a
// single place that surfaces "skipped N unsupported" / "truncated at 500"
// UNMISSABLY — components/overlays/FolderImportBanner.tsx renders it and
// stays up until the user dismisses it, unlike the status bar line (which
// the next unrelated status message silently overwrites) or the
// FolderOpenDialog (which closes immediately on Import — see
// FolderOpenDialog.test.tsx's "imports the typed folder paths" — so
// anything shown only inside the dialog would flash for zero seconds).

import { create } from "zustand";

import type { ImportSummary } from "../lib/folderImport";

interface FolderImportNoticeState {
  result: ImportSummary | null;
  set: (result: ImportSummary) => void;
  clear: () => void;
}

export const useFolderImportNotice = create<FolderImportNoticeState>(
  (set) => ({
    result: null,
    set: (result) => set({ result }),
    clear: () => set({ result: null }),
  }),
);
