# Quantized GUI port plan: five GUI fixes, two choices

Bring five GUI fixes from sibling app [quantized](https://github.com/pquarterman17/quantized) into FermiViewer. quantized shipped them in November 2026, and FermiViewer still has every one of the defects. The two apps share a stack (FastAPI, React, Zustand, Tauri) and a shell design (Inspector, Library, Shell, Stage, workshops, overlays). A defect quantized found in a shared pattern is therefore likely to be here too.

The plan also books two quantized behaviours behind owner gates, and records which recent quantized changes do not apply here.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-11-28
**Updated:** 2026-11-28 — booked from a code read of FermiViewer `main` at
`51bff4d` against quantized `main` at `a1b85ad65`. None of the five defects
has been reproduced in FermiViewer yet; each item's first sub-task is a
failing test.

---

## Context

### How the pieces fit together

Every item is frontend-only (`frontend/src`), and each sits in one shared primitive or a small group of them:

- **Draft text and number fields:** `components/spectrum/SpectrumZoomBar.tsx` (used by `workshops/EdsSpectrumImage.tsx` and `workshops/eels/EelsExploreTab.tsx`), and the `NumField` in `components/Inspector/AdjustPanel.tsx`. It writes to `setDisplay` in `store/viewer.ts`, whose history already merges consecutive edits of one control into one step.
- **Dialogs:** `components/overlays/ModalDialog.tsx`, used by `BatchDialog`, `CalibrationManager`, `ExportDialog`, `FolderOpenDialog`, `GalleryGrid`, `MetadataDialog`, `ParamDialog`, `PrefsWindow`, `ShortcutsOverlay` and `SpectralModalityPrompt`.
- **Tool windows:** `components/overlays/ToolWindow.tsx`. It closes through `closeTool` in the store.
- **Menus:** `components/Shell/DesktopMenus.tsx`.
- **Capture tools (gates only):** `components/Stage/FloatTools.tsx`, `stageFinalizers.ts` and `useStagePointers.ts`.

Each item links the quantized PR that fixed the same defect. Those PR descriptions give the root cause, the design chosen, and the evidence; read the linked PR before starting an item.

### Data / control flow

Items 1 and 2 concern the moment a typed value becomes a store write, and therefore a redraw and a history step. Item 3 concerns when an unsaved draft is thrown away. Item 4 concerns where focus goes when a window closes. Item 5 concerns what keyboard focus can reach. None of them changes what any value means.

### Dependency map

- Items 1–5 are independent, and each fits in its own commit. Items 1 and 2 both touch `AdjustPanel.tsx`'s `NumField`, so do them in the same session, item 1 first.
- Items 6 and 7 are gated (G1, G2) and touch none of the files above except `FloatTools.tsx`.

### Rules for the work

- **Reproduce first.** Each defect gets a test that fails on today's code before any fix. quantized's rule, from its [`docs/testing.md`](https://github.com/pquarterman17/quantized/blob/main/docs/testing.md), is to force the race rather than rerun the test until it fails.
- **Test the path the user takes.** Drive each test from the real entry point: the workshop tab, the Inspector card, the dialog, the menu. A helper-only test does not prove the user path.
- **Fail closed.** Items 1–5 are fixes, not new defaults. Anything the gates open ships as an opt-in preference, off by default.
- **One branch, one PR** (`fix/gui-from-quantized`), with one commit per item so each can be reverted alone. Run the full gate from the repo root (pytest, ruff, mypy, `tsc -b`, vitest, `npm run build`). New logic goes in new modules, under the ratchets in `tests/test_repo_integrity.py`. No agent co-author footers in FermiViewer commits or PR bodies.

### Not ported (checked against FermiViewer, 2026-11-28)

- **One popup editor per plot object, and Apply / OK / Cancel popups** (quantized item 50 / OG23, [#1194](https://github.com/pquarterman17/quantized/pull/1194), and item 44). FermiViewer has no axis, curve or legend editors. `components/plots/` holds only `PlotContextSurface` and `ResultVsParamPlot`.
- **Window-layout desks** (quantized [#890](https://github.com/pquarterman17/quantized/pull/890)–[#931](https://github.com/pquarterman17/quantized/pull/931)) and **Curve Fit docking** (OG15, [#1148](https://github.com/pquarterman17/quantized/pull/1148)). FermiViewer has its own workspace switcher and dock model.
- **Worksheet behaviour** (column list, Shift+F2, cell notes, named ranges). FermiViewer has no worksheet.
- **Preset bars** (quantized [#1104](https://github.com/pquarterman17/quantized/pull/1104) onward). FermiViewer already has saved batch presets with import and export (`BatchPresetControls.tsx`), plus window-width presets (`WindowPresetBar.tsx`). Extending presets to the workshop forms would be a new feature, not a port.

### Owner gates

- **G1 (item 6): tools stay armed?** Every FermiViewer capture tool turns off after one use: zoom, distance, line and box profile, polyline, angle, ROI and calibrate. In quantized, Zoom stays armed and Esc returns to Pointer (OG16), and an opt-in "Persistent plot tool" preference keeps a tool armed even through Esc. Keep one-shot tools here, or add an opt-in "keep the tool armed" preference, off by default? Calibrate should probably stay one-shot either way.
- **G2 (item 7): toolbar text labels?** quantized added an opt-in "Toolbar button labels" preference, off by default (OG18). Is it wanted for `FloatTools`?
- **G3 (item 5, optional extras): Alt+letter / F10 and a disabled-text colour?** quantized added Alt+letter to open a menu and F10 to focus the menu bar, provisionally, plus a contrast-checked colour token for disabled text. Port these too, or only the focusable disabled rows?

---

## Tier 1 — High Impact

1. **Text fields can lose the user's first input** — the quantized class fix [#1228](https://github.com/pquarterman17/quantized/pull/1228) / [#1229](https://github.com/pquarterman17/quantized/pull/1229).
   - **The defect:** a draft field that copies its prop in a mount effect has a gap between its first paint and that effect. Typing or Enter in the gap is overwritten by the old value. Where the draft starts empty, as in both places here, the first frame paints EMPTY boxes, and an immediate Enter reads an empty string.
   - **`SpectrumZoomBar.tsx:33-36`** seeds empty strings and fills them in a mount effect.
   - **`AdjustPanel.tsx:27-32`'s `NumField`** seeds an empty string and copies `value` in an effect when the field is not focused. Its `focused` ref protects typing after a focus, but not the empty first frame.
   - **The fix (quantized's pattern):**
     - Initialise the draft from the prop.
     - Resync it during render when the prop really changes, by tracking the last value seen.
     - Use no mount-time effect.
     - Keyed re-seed effects, which reset a form when a dialog opens or a dataset changes, are not value mirrors. quantized left those alone on purpose.
   - **Proof:** the race needs a non-synchronous commit, such as a lazy chunk or `root.render`. quantized's helper [`frontend/src/test/firstCommit.tsx`](https://github.com/pquarterman17/quantized/blob/main/frontend/src/test/firstCommit.tsx) renders outside `act()` and acts from a `MutationObserver` callback. That callback runs after the commit and before React's passive effects, so the test hits the gap on every run. In quantized, 6 of 9 such tests failed before the fix.
   - [ ] Port the first-commit helper into `frontend/src/test/`; failing first-commit tests for both fields
   - [ ] Render-time resync in both; the fields still follow a real prop change (undo, the history scrubber)
   - [ ] Sweep `frontend/src` for other effect-based value mirrors: fix the true mirrors, list the keyed re-seeds left alone in the PR

2. **Number fields apply every keystroke** — quantized [#966](https://github.com/pquarterman17/quantized/pull/966).
   - **The defect:** `AdjustPanel.tsx`'s `NumField` commits from `onChange` (lines 47–53) on every valid keystroke. Typing "12" as the tick font size redraws the image at size 1 first. A tick step of "0.25" commits each valid prefix on the way.
   - **Already fine:** undo. The store merges consecutive same-control edits into one history step, as pinned in `store/viewer.test.ts`. Only the half-typed redraws are wrong.
   - **The fix (quantized's behaviour, from its shared commit-draft hook):**
     - Write once, on Enter or on blur after an edit.
     - Esc on an edited field reverts it and stops there. Esc on an unedited field passes through, so the app's own Escape still works.
     - An unedited blur writes nothing, and neither does an edit to the same number ("1.50" for 1.5).
     - Invalid or out-of-range input reverts.
     - An outside change, such as undo, replaces any half-typed text.
     - Keep the live validation message while typing.
     - A field that promises live preview opts back in explicitly. Check whether any FermiViewer field needs that.
   - [ ] Failing test: typing "12" into a tick font size field writes 1 before 12
   - [ ] Commit on Enter or blur, with Esc handling and an explicit live opt-in; update tests that relied on a write per keystroke, adding Enter or blur without loosening any assertion

3. **A click outside a dialog throws away the user's edits** — quantized [#1187](https://github.com/pquarterman17/quantized/pull/1187).
   - **The defect:** `ModalDialog.tsx:124-132` closes on any mousedown on the backdrop, so a stray click discards a half-filled Batch, Export, Calibration or Metadata form.
   - **The fix (quantized's design):**
     - A dialog counts as edited after any `input` or `change` event inside its root. Every dialog then gets the rule with no per-dialog wiring, and a dialog with no inputs is never edited.
     - A newly opened dialog starts clean.
     - A backdrop click on an edited dialog shows an inline bar inside the dialog, "Discard your changes?", with Keep editing and Discard. It does not close the dialog.
     - A backdrop click on an unedited dialog still closes it silently.
     - Esc follows the same rule.
     - quantized chose an inline bar over a shared confirm dialog: a generic "Cancel" button reads as "cancel the dialog", and the bar adds no eager JS.
     - A dialog that saves as you go, possibly `PrefsWindow`, has nothing to discard and opts out.
   - [ ] Failing test: through the real open path, edit a field in `BatchDialog` or `ExportDialog`, mousedown on the backdrop, and the edits are lost
   - [ ] Edited tracking and the inline discard bar in `ModalDialog`, covering edited and unedited dialogs with both backdrop and Esc; the opt-out for live-saving dialogs

## Tier 2 — Medium Impact

4. **Tool windows: focus is not returned, and they resize from one corner** — quantized [#974](https://github.com/pquarterman17/quantized/pull/974) and [#1032](https://github.com/pquarterman17/quantized/pull/1032).
   - **Focus:** `ToolWindow.tsx:147` closes with `closeTool(kind)`, and nothing records or restores the element that opened the tool, so keyboard users land on the page body. quantized's fix:
     - Record the opener when the tool opens, and restore focus to it on close.
     - Expire the record after 1 s, and ignore it if the opener is the page body or has left the page.
     - The result is the same whichever close handler runs first.
   - **Resize:** a single grip (around line 185) resizes from the bottom-right only, and nothing visibly clamps the stored size to the viewport. In quantized, an unclamped stored height grew past the viewport and was saved, after which dragging inward did nothing. quantized's fix:
     - Eight resize handles; the bottom-right grip stays the visible one.
     - Clamp the size on mount, on viewport resize, at drag end and on keyboard resize.
     - A minimum width wide enough for the title bar's buttons.
   - [ ] Failing test: open a tool from its menu or button, close it with its ✕, and focus is not back on the opener
   - [ ] Record the opener and restore focus on close
   - [ ] Edge handles and size clamping; a window resized past the viewport is clamped and can still be dragged inward

5. **Greyed-out menu items cannot be reached from the keyboard** — quantized [#987](https://github.com/pquarterman17/quantized/pull/987).
   - **The defect:** `DesktopMenus.tsx` renders disabled entries with the `disabled` attribute (lines 223 and 322) and gives them no focus index (lines 200 and 301). Arrow keys skip them, so a keyboard or screen-reader user cannot find them or learn why they are off.
   - **The fix:**
     - Render them `aria-disabled`, focusable and inert.
     - The entry's `title` gives the reason, announced as its description.
     - Callers keep passing `disabled`, so no caller changes.
     - The optional extras wait for G3.
   - [ ] Failing test: arrow keys skip a disabled entry; after the fix it takes focus, announces its reason, and Enter runs nothing
   - [ ] `aria-disabled` rendering and focus order; update tests that asserted the skip

## Tier 3 — Nice-to-Have

6. **Keep a capture tool armed after use** — quantized OG16 and the opt-in persistent-tool preference ([`PrefsInteractionPane.tsx`](https://github.com/pquarterman17/quantized/blob/main/frontend/src/components/overlays/PrefsInteractionPane.tsx)). *Gated on G1.*
   - [ ] Build only as G1 decides

7. **Text labels on the floating toolbar's buttons** — quantized OG18, [#1147](https://github.com/pquarterman17/quantized/pull/1147). It is opt-in and off by default. The `aria-label` is unchanged and the caption is hidden from screen readers, so the name is not read twice, and the off state leaves the DOM unchanged. *Gated on G2.*
   - [ ] Build only as G2 decides

---

## Completed

(none yet)
