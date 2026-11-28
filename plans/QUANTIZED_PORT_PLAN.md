# Quantized port plan: fixes and hardening to bring over

Bring fixes from sibling app [quantized](https://github.com/pquarterman17/quantized) into FermiViewer. The two apps share a stack (FastAPI, React, Zustand, Tauri, pywebview) and a shell design (Inspector, Library, Shell, Stage, workshops, overlays). A defect quantized found in a shared pattern is therefore likely to be here too.

The plan has two workstreams: **GUI** (items 1–13) and **Platform** (items 14–22: server, desktop shell, exports, CI). It also books owner-gated behaviours and records which quantized changes do not apply here.

**Status:** Active
**Parent:** MAIN_PLAN.md
**Created:** 2026-11-28
**Updated:** 2026-11-28 (second pass) — every booked item re-read against FermiViewer `main` at `e94c5f5` and quantized `main` at `a1b85ad6`, including the quantized source for each fix. Changes from the first booking:
- Items 1 and 2 merged (one quantized hook fixes both); the dialog and tool-window items corrected where the first read was wrong; the menu item grew (no reason text exists to announce).
- Sixteen items added from a wider survey of quantized's history and audit plans.
- Plan renamed from `QUANTIZED_GUI_PORT_PLAN.md`, since it is no longer GUI-only.
- All findings come from reading code. Nothing has been reproduced or run; each item's first sub-task is a failing test.

---

## Context

### How the pieces fit together

GUI items sit in `frontend/src`, each in one shared primitive or a small group:

- **Number and draft fields:** the `NumField` in `components/Inspector/AdjustPanel.tsx`, `components/spectrum/SpectrumZoomBar.tsx`, and about 35 raw `type="number"` inputs across 19 files.
- **Dialogs:** `components/overlays/ModalDialog.tsx`, used by ten dialogs.
- **Tool windows:** `components/overlays/ToolWindow.tsx`; position lives in `store/viewer.ts` (`moveTool`).
- **Menus:** `components/Shell/DesktopMenus.tsx`, plus three hand-rolled context menus (`Stage/StageCtxMenu.tsx`, `Stage/MeasureCtxMenu.tsx`, `Library/FilmstripContextMenu.tsx`).
- **Global keys:** `hooks/useAppHotkeys.ts`.
- **Lazy loading:** `components/ChunkBoundary.tsx`, `overlays/LazyOverlays.tsx`, `overlays/ToolWindows.tsx`.

Platform items sit in `src/fermiviewer/server.py`, `server_launch.py`, `calc/table_export.py`, `src-tauri/`, and `.github/workflows/`.

### Reuse, do not rewrite

Each item names the quantized files to port. Most are small and dependency-free. quantized is public, so read them at `main`:

| quantized file | Lines | Used by item |
|---|---|---|
| `frontend/src/components/primitives/useCommitDraft.ts` | 68 | 1 |
| `frontend/src/components/primitives/BufferedNumberField.tsx` (+ test) | 90 | 1 |
| `frontend/src/test/firstCommit.tsx` | 47 | 1 |
| `frontend/src/components/overlays/figuredialogs/DiscardGuard.tsx` (+ test) | 67 | 2 |
| `frontend/src/lib/toolwindow.ts` (+ test), `overlays/ToolWindowResizeGrip.tsx` | 190, 69 | 3 |
| `frontend/src/lib/menuKeyboardNav.ts`, `overlays/ContextMenu.tsx`, `ContextMenuBoxes.tsx` | — | 4, 7 |
| `frontend/src/lib/editingTarget.ts`, `lib/deleteKey.ts`, `useGlobalShortcuts.ts` | — | 5 |
| `frontend/src/lib/lazyRegion.tsx` (+ test) | — | 6 |
| `frontend/src/lib/escapeStack.ts`, `escapeLadder.test.tsx` | — | 11 |
| `frontend/src/lib/csvCell.ts`, `csvBom.ratchet.test.ts`, `src/quantized/csv_safe.py` | — | 15 |
| `src/quantized/security.py` (`origin_allowed`), `tests/test_origin_guard.py` | — | 14 |
| `src/quantized/server_launch.py` (`_webview_start_kwargs`), `io/prefs_store.py`, `routes/prefs.py`, `frontend/src/lib/prefsServerSync.ts` | — | 16 |
| `src-tauri/nsis-hooks.nsh`, `src-tauri/tauri.conf.json`, `frontend/src/lib/tauriFileDrop.test.ts` | — | 17 |
| `src/quantized/{auth,web_guard,body_limit}.py`, `docs/api_auth.md`, `tests/test_api_auth.py` | — | 20 |
| `.github/workflows/{release,vuln-sweep,codeql}.yml`, `osv-scanner.toml`, `tools/gate.py` | — | 18, 19 |
| `docs/testing.md`, `frontend/src/test/untilState.ts`, weak-wait ratchet in `architecture.test.ts` | — | 21 |

Class names differ (`qz-`/`qzk-` there, `fvd-` here), and quantized's stores (`useApp`) are not FermiViewer's (`useViewer`). Port the logic and tests; rewire the store calls.

### Dependency map

- **1** is self-contained. Do the `NumField` and `SpectrumZoomBar` first, then the sweep.
- **3** and **10** both touch `ToolWindow.tsx`; do them in one session.
- **4** and **7** share keyboard navigation; do 7 first so menus have one implementation to make `aria-disabled`.
- **5** must land before G3's Alt+letter extra, or Alt+F would open File and also arm a tool.
- **11** (gated) builds on 5 and 7.
- **14** before **20**: the origin fix is small and stands alone; the token is the larger follow-on.
- **16**'s one-line pywebview fix is independent of its backend-prefs part.
- Platform items are otherwise independent of the GUI items.

### Rules for the work

- **Reproduce first.** Each defect gets a test that fails on today's code before any fix. quantized's rule, from its [`docs/testing.md`](https://github.com/pquarterman17/quantized/blob/main/docs/testing.md), is to force the race rather than rerun the test until it fails. If a defect does not reproduce, close the item with a note instead of fixing it.
- **Test the path the user takes.** Drive each test from the real entry point: the workshop tab, the Inspector card, the dialog, the menu.
- **Fail closed.** Fixes are not new defaults. Anything a gate opens ships as an opt-in preference, off by default.
- **Small PRs by workstream**, one commit per item so each can be reverted alone. Run the full gate from the repo root (pytest, ruff, mypy, `tsc -b`, vitest, `npm run build`). New logic goes in new modules, under the ratchets in `tests/test_repo_integrity.py`.

### Not ported (checked against FermiViewer, 2026-11-28)

- **Popup editors per plot object, Apply / OK / Cancel popups, window-layout desks, Curve Fit docking, worksheet behaviour, preset bars.** No FermiViewer analogue, or FermiViewer has its own model.
- **Toaster fixes, frontend autosave and recovery, second-tab guard.** FermiViewer has no toaster, and its sessions live on the backend.
- **Large-payload-by-handle, result envelopes, `heavy_imports` lock.** Tied to quantized's data model or to matplotlib.
- **Bundle-size budget, Playwright e2e.** FermiViewer has module-size ratchets and no e2e harness; adding one is a project, not a port.
- **Already equivalent here:** atomic project and store writes, Host/Origin DNS-rebinding guard, shell port fallback, sidecar kill on close, updater, Dependabot, tag/version guard, object-URL cleanup, wheel listeners, corrupt-JSON `localStorage` reads, dialog focus return from menus.

### Owner gates

- **G1 (item 12): tools stay armed?** Every capture tool here turns off after one use. In quantized, Zoom stays armed and an opt-in preference keeps any tool armed. Keep one-shot, or add an opt-in preference, off by default?
- **G2 (item 13): toolbar text labels?** An opt-in preference in quantized, off by default. Wanted for `FloatTools`?
- **G3 (item 4, extras): Alt+letter and F10 for the menu bar?** Needs item 5 first.
- **G4 (item 11): one Esc, one layer?** Today one Esc exits compare, cancels the tool, closes shortcuts and clears the selection together. That may be intended. Move to quantized's ladder (innermost layer only)?
- **G5 (item 19): trim the PR test matrix?** CI runs 12 backend legs on every push. quantized runs a trimmed set on PRs and the full matrix nightly.
- **G6 (item 20): per-launch API token?** It closes the "any local process can call the API" gap, but the shell must stop adopting an already-running server.
- **G7 (item 22): lock an open `.fvp`?** Only worth building if two instances editing one project is a real workflow.

---

# GUI workstream

## Tier 1 — High Impact

1. **Number fields apply half-typed values, and snap back while typing** — quantized [#966](https://github.com/pquarterman17/quantized/pull/966), [#1228](https://github.com/pquarterman17/quantized/pull/1228), [#1229](https://github.com/pquarterman17/quantized/pull/1229).
   - **Per-keystroke writes:** `AdjustPanel.tsx:47-53`'s `NumField` commits on every valid keystroke, so typing "12" redraws at 1 first. `ScaleBarCard.tsx:159-162` and `TiltCorrectionCard.tsx:33-41` do the same.
   - **Snap-back:** fields that bind `value` to the store number and write `Number(text) || fallback` cannot be cleared: deleting the text snaps to the fallback mid-edit. `MeasurePanel.tsx:177` (`|| 1`), `EelsQuantifyPanel.tsx:82,92` (`|| 200`, `|| 10`), `TiltCorrectionCard.tsx` (`|| 0`). This is the bug quantized's buffered field was written for.
   - **First-commit gap (lower severity than first booked):** `SpectrumZoomBar.tsx:33-36` seeds empty drafts and fills them in a mount effect, so the first frame paints empty boxes and typing in that gap is overwritten. In `NumField` the `focused` ref already protects typing; only the empty first paint remains. A user is unlikely to hit this by hand; it matters for tests and lazy mounts.
   - **Also check:** `SpectrumZoomBar.tsx:68` commits on every blur, edited or not. On an unzoomed spectrum (`range === null`), tabbing through may write a rounded range and flip the bar to "zoomed". Write the test; fix if it fails.
   - **The fix:** port `useCommitDraft.ts` as is. It seeds from the prop, resyncs during render, and has no mount effect, so it closes all three shapes. Its behaviour:
     - Write once, on Enter or on blur after an edit. An unedited blur writes nothing; neither does the same number retyped ("1.50" for 1.5).
     - Esc on an edited field reverts it. (`useAppHotkeys.ts:36-42` already ignores keys from inputs, so no pass-through rule is needed here.)
     - Invalid or out-of-range input reverts; an outside change such as undo replaces half-typed text.
     - `live` opts a field back in to per-keystroke writes. Keep `NumField`'s live validation message.
   - **Already fine:** undo. The store merges same-control edits into one step (`store/viewer.test.ts`).
   - [ ] Port `useCommitDraft` and `firstCommit.tsx`; failing tests: "12" writes 1 before 12, and a first-commit test for `SpectrumZoomBar`
   - [ ] Build `NumField` and `SpectrumZoomBar` on the hook; fields still follow undo and the history scrubber
   - [ ] Sweep the other `type="number"` inputs. Convert those that write to the store or call the backend per keystroke; leave local-draft fields (for example `CalibrationCard`, `DefectWorkshop`, `FourDScanShape`) and list them in the PR. Add Enter or blur to tests that relied on a write per keystroke, without loosening any assertion

2. **A click outside a dialog throws away the user's edits** — quantized [#1187](https://github.com/pquarterman17/quantized/pull/1187).
   - **The defect:** `ModalDialog.tsx:124-126` closes on any backdrop mousedown. A stray click discards a half-filled Batch, Export, Calibration, Metadata or **Preferences** form. (`PrefsWindow` is a draft-and-Save dialog, `PrefsWindow.tsx:153,192`; it is the most exposed, not an opt-out as first booked.)
   - **The fix:** port `useDiscardGuard` and `DiscardBar` from `DiscardGuard.tsx` into `ModalDialog`.
     - A dialog counts as edited after any `input` or `change` event inside its root (`onInputCapture` / `onChangeCapture`), so no dialog needs wiring.
     - A backdrop click on an edited dialog shows an inline bar, "Discard your changes?", with Keep editing and Discard. An unedited dialog still closes silently.
     - **Esc stays an explicit cancel** and closes without asking. That is quantized's actual design; the first booking had it wrong. With the bar showing, Esc means Keep editing.
     - quantized's hook uses its escape stack. `ModalDialog` handles Esc in its own `onKeyDown` (`:91-99`), so handle the bar's Esc there instead.
   - [ ] Failing test: through the real open path, edit a field in `BatchDialog` and in `PrefsWindow`, mousedown on the backdrop, and the edits are lost
   - [ ] Guard and bar in `ModalDialog`; cover edited and unedited, backdrop and Esc

3. **Tool windows can be lost off-screen, and closing one drops keyboard focus** — quantized [#1032](https://github.com/pquarterman17/quantized/pull/1032), [#974](https://github.com/pquarterman17/quantized/pull/974), its GUI plan item 10.
   - **Off-screen (new, the real risk):** `ToolWindow.tsx:114-117` clamps a drag only to x, y ≥ 0. A window can be dragged past the right or bottom edge until its title bar is unreachable, and nothing re-clamps when the app window shrinks. Port `clampToolWindowPos` from `lib/toolwindow.ts` and apply it at drag end and on viewport `resize`.
   - **Stuck drags:** neither the title drag (`:106-124`) nor the resize grip (`:185-228`) handles `pointercancel`, so an interrupted drag stays live. Add `onPointerCancel`.
   - **Resize from one corner:** port `resizeToolWindow` and the eight handles from `ToolWindowResizeGrip.tsx`; the bottom-right grip stays the visible one. West and north drags move `x`/`y`, so they write through `moveTool`.
   - **Not a defect here:** the stored size is already clamped on restore and during a drag (`:31-35`, `:200-216`). quantized's "oversize stored, dead zone" bug is absent.
   - **Focus:** `closeTool(kind)` at `:147` restores nothing. `ModalDialog.tsx:68-89` already has the right pattern (record `document.activeElement` on mount; restore on unmount if still connected and visible); reuse it. quantized's `focusReturn.ts` solves a race specific to its layout manager and is not needed. A tool opened from a menu has an opener that is gone by close; fall back to the menu-bar button.
   - [ ] Failing tests: drag a window past the right edge and it cannot be dragged back; open a tool from its button, close with ✕, focus is on `<body>`
   - [ ] Position clamp at drag end and on viewport resize; `pointercancel` on both drags
   - [ ] Record the opener and restore focus on close
   - [ ] Edge handles through `resizeToolWindow`

## Tier 2 — Medium Impact

4. **Greyed-out menu items cannot be reached, and give no reason** — quantized [#987](https://github.com/pquarterman17/quantized/pull/987).
   - **The defect:** `DesktopMenus.tsx` renders disabled entries with `disabled` (`:223`, `:322`) and no focus index (`:200`, `:301`), so arrow keys skip them. `FilmstripContextMenu.tsx:124` does the same.
   - **Larger than first booked:** `MenuEntry` (`:5-12`) has no field for a reason, and none of the 97 `disabled:` call sites in `Shell/menus/` supplies one. Focusable rows that say nothing help little.
   - **The fix:** render them `aria-disabled`, focusable and inert. Add an optional `disabledReason` to `MenuEntry`, shown as the `title` and wired as the accessible description. Fill reasons by group (most are "open an image first" or "needs a calibrated image").
   - [ ] Failing test: arrow keys skip a disabled entry; after the fix it takes focus, announces its reason, and Enter runs nothing
   - [ ] `aria-disabled` rendering and focus order in all menu surfaces; `disabledReason` on the common groups

5. **A key a focused control already handled also fires the global shortcut** — quantized `useGlobalShortcuts.ts` (its PR #139 and audit P3.3), `1e2ebd4b`.
   - **The defect:** `useAppHotkeys.ts:32-46` skips inputs and modals but never checks `defaultPrevented`. `Library/Filmstrip.tsx:158-176` handles an arrow key and calls `preventDefault`; the window handler then cycles the image again, so one press appears to move two. The same shape is in `AfmSurfaceWorkshop.tsx:378-389` and `WorkspaceSwitcher.tsx:100-125`. `spectrumWindowGestures.ts:115` already patches one site by hand.
   - **Modifiers:** only Ctrl/Meta is tested (`:48`, `:91`). Alt+D or Alt+F arm a tool; Shift+Delete and Alt+Backspace reach the close-image branch (`:193-240`). Redo is Ctrl+Shift+Z only; quantized also takes Ctrl+Y.
   - **Tool windows:** Delete, Backspace and tool letters fire while focus is on a button inside a non-modal tool window. Decide per key; quantized exempts tool windows from the destructive ones.
   - [ ] Failing tests: one ArrowDown in the filmstrip moves two images; Alt+F arms a tool; Shift+Delete closes an image
   - [ ] `defaultPrevented` and Alt/Shift guards; Ctrl+Y redo; tool-window exemption for destructive keys; remove the hand patch

6. **A panel that fails to load once never recovers, and render bugs are reported as load failures** — quantized `lib/lazyRegion.tsx`, `lib/toolLoadFailure.tsx`.
   - **The defect:** the `lazy()` components are module constants (`LazyOverlays.tsx:8-16`, `ToolWindows.tsx:7-26`, `App.tsx:34-36`), and React caches a rejected `lazy()`. After one failed chunk fetch, reopening shows the same error until a full reload. The comment at `LazyOverlays.tsx:38` says otherwise.
   - **Mislabel:** `ChunkBoundary.tsx:29-43` catches every error and titles it "failed to load", which hides real render bugs.
   - **The fix:** port `lazyRegion.tsx`: a fresh `lazy()` per retry, and only chunk-load errors get the retry UI; other errors go to the app error boundary.
   - [ ] Failing test: reject the import once, close, reopen, and the dialog still fails
   - [ ] Per-instance retry; separate load failures from render errors; correct the comment

7. **Right-click menus open off-screen and cannot be used from the keyboard** — quantized `overlays/ContextMenu.tsx`, [#802](https://github.com/pquarterman17/quantized/pull/802).
   - **Off-screen:** raw click coordinates at `StageCtxMenu.tsx:65`, `MeasureCtxMenu.tsx:148` (a tall menu) and `FilmstripContextMenu.tsx:104`, with no flip, clamp or max-height. Only `plots/PlotContextSurface.tsx:83-85` clamps.
   - **Keyboard:** the two stage menus have no `role="menu"`, no arrow keys, no focus move and no Esc. Esc clears the selection behind the menu and the menu stays open.
   - **The fix:** one small shared context-menu shell (placement, roles, arrow keys, Esc) from quantized's `ContextMenu` and `menuKeyboardNav.ts`, used by all three.
   - [ ] Failing tests: open each menu at the bottom-right corner and it overflows; Esc leaves the stage menu open
   - [ ] Shared shell; migrate the three menus

8. **A slow profile response lands on the wrong image** — quantized [#856](https://github.com/pquarterman17/quantized/pull/856), [#857](https://github.com/pquarterman17/quantized/pull/857).
   - **The defect:** `Stage/useMeasureRefresh.ts:36-50` and `Inspector/MeasurePanel.tsx:97-99` call `setProfile` / `setRoiStats` when the request resolves, with no check that the image is still active and no latest-wins guard. Switch images, or drag a measure quickly, and a stale result can overwrite the current one.
   - FermiViewer's own audit (2026-10-31) named this as a follow-up; it was never booked. `stageFinalizers.ts:66-76` already guards by image, and `hooks/useLatestRequest.ts` is the in-repo tool.
   - [ ] Failing test with a forced order: two requests, the first resolves last, and the older profile is shown
   - [ ] Latest-wins plus active-image guard at both sites

## Tier 3 — Nice-to-Have

9. **Storage that is full or blocked can break pan and zoom.** `localStorage.setItem` runs unguarded before the state update at `store/viewer.ts:328-330` (every pan/zoom tick) and `:413-415`, and in `lib/prefs.ts:240`, `lib/batchRecipePresets.ts:95`, `lib/colormaps.ts:135`. `fv_views` is keyed by a per-open uuid and pruned only on close, so it grows. `lib/macro.ts:74-84` `trySetItem` is the pattern to reuse.
   - [ ] Route writes through `trySetItem`; prune `fv_views` at startup

10. **Screen-reader and keyboard gaps in the shell** — quantized [#756](https://github.com/pquarterman17/quantized/pull/756), [#762](https://github.com/pquarterman17/quantized/pull/762).
    - `Shell/StatusBar.tsx:29` is a plain `<span>`. FermiViewer has no toaster, so the status line is the only feedback for copy, undo and errors; give it `role="status"`.
    - `ToolWindow.tsx:127-148` has no role or name, and its close button has only a `title`.
    - The Inspector width grip (`Inspector.tsx:35-62`) is mouse-only; port the keyboard handling from `primitives/panelResize.ts`.
    - [ ] Live status region; tool-window role and labels; keyboard Inspector grip

11. **One Esc, one layer** — quantized `lib/escapeStack.ts`. *Gated on G4.* `useAppHotkeys.ts:243-249` does four things on one press, and `ToolWindow.tsx:97-104` adds a window-level Esc that also fires while typing in a field inside the tool.
    - [ ] Build only as G4 decides. The tool-window listener firing from inside a field is a fix regardless

12. **Keep a capture tool armed after use** — quantized OG16 and [`PrefsInteractionPane.tsx`](https://github.com/pquarterman17/quantized/blob/main/frontend/src/components/overlays/PrefsInteractionPane.tsx). *Gated on G1.*
    - [ ] Build only as G1 decides

13. **Text labels on the floating toolbar's buttons** — quantized [#1147](https://github.com/pquarterman17/quantized/pull/1147). Opt-in and off by default; the `aria-label` is unchanged and the off state leaves the DOM unchanged. *Gated on G2.*
    - [ ] Build only as G2 decides

**Deferred, not booked:** 21 `window.confirm` / `window.prompt` calls sit outside the dialog system (`Shell/menus/fileEditMenus.ts`, `Inspector/RegionWorkspaceCard.tsx`, `Stage/MeasureCtxMenu.tsx` and others). quantized replaced its own with `ConfirmDialog`. This is a larger migration with its own design; book it separately if wanted.

---

# Platform workstream

## Tier 1 — High Impact

14. **Any page on another localhost port can call the API** — quantized BUG-030, `security.py` `origin_allowed`.
    - **The defect:** `server.py:80-97` accepts any Origin whose host is `localhost`, `127.0.0.1` or `::1`, on any port, and any `tauri://` origin. Another local dev server or local web app open in the browser can call path-taking routes. `tests/test_csrf_guard.py:27-28` pins the loose behaviour.
    - **The fix (quantized's):** accept only the server's own origin, derived from the request's vetted `Host` header and scheme, plus the exact Tauri origins, plus the Vite dev origin only under `--dev`.
    - [ ] Failing test: `Origin: http://localhost:9999` against a server on another port is accepted
    - [ ] Own-origin check; dev origin behind the dev flag; update the pinned tests

15. **CSV exports can carry live formulas, and non-ASCII units open garbled in Excel** — quantized 0.28.0, `csv_safe.py`, `lib/csvCell.ts`.
    - **Formulas:** labels and names come from instrument files. `calc/table_export.py:146-156` returns `str(value)` and writes headers raw (`:121`); `frontend/src/lib/resultsExport.ts:31-33` only quotes. A label starting with `=`, `+`, `-` or `@` runs as a formula when the file is opened. Port `neutralize_formula` (it leaves plain negative numbers alone).
    - **Encoding:** CSV blobs are written without a BOM at `lib/profileCsv.ts:225`, `lib/grainsCsv.ts:137`, `lib/eelsQuantCsv.ts:64`, `lib/resultsExport.ts:104`, `workshops/EdsSpectrumImage.tsx:71` and `workshops/AtomColumnPanel.tsx:271`. Excel on Windows shows µ, Å and ± as mojibake. Port `csvBlob` and the ratchet test that keeps new writers on it.
    - [ ] Failing tests: a label `=1+1` is exported unescaped; a profile CSV with µm has no BOM
    - [ ] One shared CSV writer on each side; migrate every writer; ratchet

16. **Preferences can vanish between launches.**
    - **pywebview (one line):** `server_launch.py:128` calls bare `webview.start()`. pywebview 4+ defaults to `private_mode=True`, and `pyproject.toml` pins `>=6.0`, so `fv --desktop` likely discards `localStorage` (prefs, recents, presets, macros) on exit. Port quantized's `_webview_start_kwargs` (0.45.0). Confirm on a desktop first; this has not been run.
    - **Port changes:** prefs live in origin-scoped `localStorage` (`lib/prefs.ts:165,240`). When port 8000 is busy the server and shell pick another (`server.py:441-445`, `src-tauri/src/main.rs:43-51`), which is a new origin with empty storage. Running quantized beside FermiViewer triggers it. quantized moved prefs to the backend ([#1024](https://github.com/pquarterman17/quantized/pull/1024)).
    - [ ] Reproduce the pywebview loss; pass `private_mode=False` and a storage path
    - [ ] Backend prefs store with one-time migration from `localStorage` (size M; do after the one-line fix)

17. **Desktop shell: file drops and upgrades on Windows.**
    - **Drops:** Tauri v2 intercepts OS file drops unless the window sets `dragDropEnabled: false`. FermiViewer's `tauri.conf.json` lacks the key, and `App.tsx:102-124` relies on the HTML5 `drop` event, so dropping a file on the installed Windows app likely does nothing. quantized sets the key and pins it with `tauriFileDrop.test.ts`. Not yet reproduced on Windows.
    - **Upgrades:** no installer hook stops a running or orphaned `fv-server.exe`, so an in-place upgrade can fail with "Error opening file for writing". Port `nsis-hooks.nsh` and wire `bundle.windows.nsis.installerHooks`.
    - **CSP:** `tauri.conf.json:23` has `"csp": null`. Set a policy as part of item 20, or alone if G6 is declined.
    - [ ] Confirm the drop failure on an installed build; set the key and port the guard test
    - [ ] NSIS pre-install and pre-uninstall hooks

## Tier 2 — Medium Impact

18. **Release integrity and scanning.**
    - `release.yml` publishes no `SHA256SUMS`, and its sidecar smoke checks only `/api/health` and `/` (`:127-167`), which would not catch a PyInstaller spec that drops data files. Port quantized's `checksums` job and its package-data smoke steps.
    - No scheduled vulnerability sweep. Port `vuln-sweep.yml` and `osv-scanner.toml`. Check whether CodeQL default setup is already on in the repo settings before adding `codeql.yml`.
    - [ ] Checksums job; deeper sidecar smoke
    - [ ] Weekly OSV sweep; CodeQL if not already enabled

19. **CI cost and lint.**
    - `ci.yml` has no `concurrency` block, so superseded runs keep going; no uv or npm cache; no `pytest-xdist`. Each is a small port (quantized `0c140abc`, `17c1b470`).
    - The frontend has no eslint config or `lint` script. quantized runs eslint with `--max-warnings=0`.
    - A trimmed PR matrix with the full matrix nightly waits on G5.
    - [ ] Concurrency cancel, caches, xdist
    - [ ] eslint with a zero-warning gate (expect a first cleanup pass)

20. **Per-launch API token, CSP and request-body cap** — quantized 0.28.0, `docs/api_auth.md`. *Gated on G6.* Any local process, or another user on a shared machine, can call `/api/*`; Host and Origin checks stop browsers only. Size L. The shell must stop adopting an already-running server (`main.rs:262-270`), which interacts with single-instance.
    - [ ] Build only as G6 decides

## Tier 3 — Nice-to-Have

21. **Test determinism** — quantized `docs/testing.md`, `TEST_DETERMINISM_PLAN.md`. About 64 `waitFor(() => expect(mock).toHaveBeenCalled…)` sites across 27 test files wait on a mock instead of on state, with no ratchet; vitest runs at the 5 s default timeout; `tests/test_store_lock.py:265` and `tests/test_launch_dir.py:166` assert tight wall-clock bounds. Port `untilState.ts` and the weak-wait ratchet, frozen at today's count.
    - [ ] Ratchet at the current count; raise `testTimeout`; loosen the two wall-clock asserts

22. **Lock an open `.fvp` across instances** — quantized `desktop_project_lock*.py`. *Gated on G7.* Each save is atomic, so two instances lose updates rather than corrupt the file.
    - [ ] Build only as G7 decides

---

## Completed

(none yet)
