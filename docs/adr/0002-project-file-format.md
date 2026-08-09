# ADR 0002 — Project file format (`.fvp`)

**Status:** Accepted
**Date:** 2026-08-09
**Supersedes:** the v1 workspace format (`<stem>.json` + `<stem>.npz`)
**Schema:** [`docs/schema/fvp-v2.schema.json`](../schema/fvp-v2.schema.json)

## Context

FermiViewer's v1 workspace format is a JSON manifest beside an `.npz`
holding every image's pixels. It works, but it was built for a flat
session of a few images and does not carry a many-sample study:

- **Two sibling files get separated.** Copying, emailing or syncing one
  without the other yields an unloadable pair, and the save has to
  commit the manifest last to stay crash-safe.
- **Everything is embedded, always.** A study of 10 samples × 20 frames
  at 1536×1103 uint16 is ~500–700 MB compressed. Every save rewrites all
  of it.
- **Source provenance is absent.** v1 keeps pixels, not where they came
  from, so a project cannot be reconnected to its folders on another
  machine.
- **The interesting state is opaque.** Groups, measurements and (now)
  per-sample parameter values live inside `client_state`, a blob the
  backend passes through unexamined. Nothing can validate them, and a
  parameter value is scientific data, not UI chrome.

## Decision

A project is a **single ZIP container with the extension `.fvp`**,
holding a schema-validated `manifest.json` plus optional per-image pixel
and thumbnail entries.

```
project.fvp                    (ZIP, DEFLATE)
├── manifest.json              required — validated against the schema
├── pixels/<image-id>.npy      required for each image with embedded: true
├── thumbs/<image-id>.png      optional, <= 256 px on the longest edge
└── <future dirs>              ignored by readers that do not know them
```

### 1. Single container

One file cannot be separated in transfer, and it makes the save
**atomic by construction**: write a temp sibling, `fsync`, one
`os.replace`. That retires v1's manifest-last commit ordering, which
existed only because two files had to agree.

A ZIP is deliberately boring: `unzip project.fvp` or
`python -m zipfile -l project.fvp` inspects it with no FermiViewer
present, and `.npy` entries can be read individually, so opening one
image out of a hundred does not inflate the rest.

### 2. Two payload modes

`payload_mode` distinguishes them; both are the same format and the same
reader.

| | `light` | `bundle` |
|---|---|---|
| Written by | Save Project (everyday) | Export Project Bundle |
| Source pixels | referenced, `embedded: false` | embedded, `embedded: true` |
| Derived images | **always embedded** | embedded |
| Measures, samples, params | always | always |
| Thumbnails | always | always |
| Typical size | 2–20 MB | 250–700 MB |
| Needs source folders | yes | no |

Derived images (filter results, cropped databar strips) have no file of
their own, so they are embedded in **both** modes — otherwise a light
save would silently discard work. Thumbnails are always embedded so a
project browses and reviews with its data absent.

### 3. Portable references: one data root

Light mode stores each source as a POSIX-style path **relative to a
single declared data root**, plus the root's absolute path as a *hint*.

Resolution order on load, per image:

1. `data_root_hint` + `rel`
2. the directory containing the `.fvp` + `rel`
3. any root the user has re-pointed this session
4. unresolved

Storing one root rather than N absolute paths means relocation is **one
folder pick that fixes every image at once**. Paths are always written
with forward slashes and normalised on load, so a project written on
Windows opens on macOS. `size_bytes` is recorded per image as a cheap
sanity check that a re-pointed folder holds the expected data.

### 4. Unresolved images are never dropped

An image that does not resolve loads as an **unavailable placeholder**
that keeps its name, sample membership, parameters and measurements, and
**saving preserves its reference**. Opening a project on a machine
without the data and pressing save must not be able to destroy it. A
"Locate folder…" action can be invoked at any time, repeatedly, so
samples that moved to different folders can each be re-pointed.

### 5. Specified sections, not one opaque blob

Scientific content is promoted out of `client_state` into sections the
schema validates:

- `images` — identity, kind, axis calibration, metadata, source reference
- `samples` — named ordered member sets, optional parent, **parameter
  values with units**
- `measures` — per-image annotations and regions, including areas

Genuinely presentational state stays opaque under `ui_state` (`views`,
`display`, `overlay`, `savedRois`, `sbsPanes`, `sbsRows`, `sbsCols`,
`browseScale`). The split is the point: a schema cannot check a
parameter value it cannot see, and `ui_state` is exactly the set whose
shape we do not want to freeze.

A **sample is an `ImageGroup`** — the same primitive the compare grid
already steps through (`frontend/src/lib/groups.ts`), extended with
`params` and `parent`. Projects do not get a second grouping mechanism.

`primary_param` names which parameter is the independent variable, so
"result vs parameter" plots and montage ordering need no per-use prompt.

### 6. Validation and forward compatibility

`manifest.json` is validated against the schema on **load**, failing
with a message naming the offending path (`images[3].rel`). Unknown keys
are **preserved verbatim on save**, so a project written by a newer
build and re-saved by an older one does not lose what it did not
understand. Versions therefore are not one-way.

`version` is `2`. `load` accepts a v1 pair and upgrades it in memory;
the next save writes `.fvp`. v1 is read-only legacy from here.

## Consequences

**Good.** One file to move; atomic saves; everyday saves are megabytes;
projects survive moved data and a machine change; the format is
documented, machine-checkable, and inspectable with standard tools;
derived work can never be silently lost.

**Costs.** Two write paths to build and test. Light-mode projects depend
on their source folders and need the placeholder/relocate UI. Migration
code for v1 must be carried. Promoting groups and measures out of
`client_state` touches every save/load call site.

**Rejected alternatives.** *Always self-contained* — every save rewrites
hundreds of MB. *Always referenced* — cannot hold derived images, so it
was never actually pure. *Incremental deduplicated bundle* — the right
end state if project sizes become painful, but a lot of machinery before
the simple version has been felt to hurt. *Keep two sibling files* —
loses atomicity and gets separated in transfer, which is the problem
being solved.

## Verification

- Round-trip: save → load → deep-equal on images, samples, params,
  measures, and `ui_state` passthrough.
- Unknown-key preservation: inject a key the reader does not know, load,
  save, assert it survives.
- v1 migration: a v1 `.json`/`.npz` pair loads and re-saves as `.fvp`
  with nothing lost.
- Path portability: a manifest written with a Windows-style hint
  resolves on POSIX via the project-relative fallback.
- Missing sources: an unresolvable reference loads as a placeholder and
  **survives a save** (the no-data-loss assertion).
- Atomicity: a save interrupted before commit leaves the previous
  `.fvp` intact.
