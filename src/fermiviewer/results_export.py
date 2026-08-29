"""Self-contained result export archives — roadmap item 2's last box.

`results_report` builds a report MANIFEST. An output whose array is over
`MAX_INLINE_ARRAY_VALUES` contributes only its `member` name, and that
member is a path inside the *originating* `.fvp`: saving the manifest for
a large table or curve yields a document that cannot reconstruct what it
names. This module closes that gap by writing a container that carries
the member payloads beside the manifest, so every citation in it resolves
*within the archive*.

## Why the layout is the project's layout

The archive stores arrays at `results/<result-id>/<n>.npy` — byte-for-byte
the entry name `io.project_results.prepare_results` allocates for the same
output inside a `.fvp`. That is deliberate and is the whole trick: the
manifest's `member` field needs no rewriting, no parallel "path" key, and
no second convention to keep in sync. A reader resolves `member` against
the archive exactly as it would against the project.

`prepare_results` is reused rather than reimplemented, so an export also
inherits its validation — duplicate record ids, unknown kinds, unsafe
member names — and so a record captured in a session whose project was
never saved (member still `None`) gets one allocated here on the same
rule as a save would.

## `values` and `.npy` are the same array, not the same bytes

Every output that has an array is written as `.npy` AND, when small
enough, inlined into the manifest as `values`. They come from one array in
one pass and cannot disagree about magnitude — but they are not identical
renderings: `values` goes through `finite_json`, so NaN and ±Inf become
`null` (indices preserved), while the `.npy` holds the exact IEEE values.
**The `.npy` is authoritative.** `values` is a convenience for a reader
that has JSON but not numpy, and `README.txt` says so inside the archive.

## Determinism

The archive is byte-reproducible for the same records and the same
`app_version`, apart from `generated_at` — and reproducible ACROSS HOSTS,
not merely across two runs on one machine. Every header field `zipfile`
would otherwise take from the environment is pinned: the timestamp (else
the wall clock), the mode (else the umask), and `create_system` (else
`sys.platform`, which differs on Windows). See `_entry`. An exported
archive is a citable artifact someone may hash; the `.fvp` container has
no such requirement, which is why `write_result_members` is not reused
for the member entries here.

An output whose member was lost before the export (`array is None` after a
degraded load) writes no entry. The manifest keeps the citation and the
bundle's warnings already say the record is degraded; inventing zeros to
fill the archive would be worse than a gap the manifest explains.

Pure layer: stdlib + numpy + `fermiviewer.io.*` + `fermiviewer.results_*`.
Takes `app_version` as an argument and knows nothing about HTTP.
"""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import IO, Any

import numpy as np

from fermiviewer.io.project_results import prepare_results
from fermiviewer.io.results_model import ResultRecord
from fermiviewer.results_report import ReportBundle, build_report, bundle_payload, utc_now

__all__ = [
    "ARCHIVE_VERSION",
    "MANIFEST_NAME",
    "METHODS_NAME",
    "README_NAME",
    "ResultArchive",
    "build_archive",
    "archive_bytes",
    "write_archive",
]

#: Layout version for the ARCHIVE — which entries exist and where. Bumped
#: when the file layout changes. Distinct from `results_report`'s
#: `REPORT_VERSION`, which versions the manifest's own structure: an
#: archive can be relaid out without the manifest changing, and vice
#: versa. Both are stamped into `manifest.json`.
ARCHIVE_VERSION = 1

MANIFEST_NAME = "manifest.json"
METHODS_NAME = "methods.txt"
README_NAME = "README.txt"

#: The ZIP epoch. `zipfile` cannot store a date before 1980, so this is the
#: earliest fixed stamp available, and a fixed stamp is what makes two
#: exports of the same records hash alike.
_FIXED_DATE = (1980, 1, 1, 0, 0, 0)

#: `ZipInfo.create_system` for Unix. Pinned so a Windows-built archive is
#: byte-identical to a Linux one; see `_entry`.
_UNIX_CREATE_SYSTEM = 3

_README = """\
FermiViewer result export
=========================

This archive is self-contained: every array cited by the manifest is
included here, so nothing in it requires the project it came from.

  {manifest}   the report manifest: records, resolved parameters,
                   calibration snapshots, warnings and generated methods
  {methods}    the methods prose on its own, for pasting into a draft
  results/<result-id>/<n>.npy
                   one output's array, in NumPy .npy format, where <n> is
                   the output's index within that record

Resolving an array
------------------
Each output entry in the manifest carries a "member" field naming its
entry in this archive. Load it with numpy:

    import json, numpy, zipfile
    with zipfile.ZipFile("<this file>") as zf:
        manifest = json.loads(zf.read("{manifest}"))
        output = manifest["results"][0]["outputs"][0]
        with zf.open(output["member"]) as fh:
            values = numpy.load(fh, allow_pickle=False)

An output whose "member" is null never had an array. An output whose
"member" names an entry that is absent from this archive was already
degraded when the export ran — its array had been lost from the source
project — and the manifest's warnings say so, naming the record.

Two views of the same array
---------------------------
Small arrays also appear inline as the output's "values". That copy is
JSON-safe: NaN and infinity are written as null, with positions kept. The
.npy entry holds the exact values and is authoritative wherever the two
could differ.

Generated by FermiViewer {app_version} at {generated_at}.
Archive layout version {archive_version}; report manifest version {report_version}.
"""


@dataclass(frozen=True)
class ResultArchive:
    """An export archive, assembled but not yet serialized.

    `manifest` is the JSON-safe dict written as `manifest.json`; `records`
    are the prepared records whose arrays become the `.npy` entries. Kept
    separate from the bytes so a caller can inspect or test the content
    without unzipping, and so `archive_bytes` stays a pure serializer.
    """

    manifest: dict[str, Any]
    records: tuple[ResultRecord, ...]
    readme: str
    methods: str

    @property
    def members(self) -> tuple[str, ...]:
        """Entry names this archive will actually write, in write order —
        the citations a reader can expect to resolve."""
        return tuple(
            output.member
            for record in self.records
            for output in record.outputs
            if output.member is not None and output.array is not None
        )


def build_archive(
    records: Sequence[ResultRecord],
    *,
    app_version: str,
    clock: Callable[[], str] = utc_now,
) -> ResultArchive:
    """Assemble an export archive over `records`, in the order given.

    Validates and allocates member names through `prepare_results`, so a
    malformed selection raises `ProjectFormatError` here — before any bytes
    are produced — rather than yielding a half-written download.
    """
    prepared = prepare_results(records)
    bundle: ReportBundle = build_report(
        prepared, app_version=app_version, clock=clock
    )
    manifest = bundle_payload(bundle)
    manifest["archive_version"] = ARCHIVE_VERSION
    readme = _README.format(
        manifest=MANIFEST_NAME,
        methods=METHODS_NAME,
        app_version=bundle.app_version,
        generated_at=bundle.generated_at,
        archive_version=ARCHIVE_VERSION,
        report_version=bundle.version,
    )
    return ResultArchive(
        manifest=manifest,
        records=prepared,
        readme=readme,
        methods=bundle.methods,
    )


def _entry(name: str) -> zipfile.ZipInfo:
    """A ZIP entry header with every host-derived field pinned.

    Three of them, each an environment input the archive must not inherit
    if two exports of one selection are to hash alike:

    * the timestamp, which would otherwise be the wall clock;
    * the mode, which `zipfile` derives from the process umask;
    * `create_system`, which `ZipInfo.__init__` sets from `sys.platform` —
      ``0`` on Windows and ``3`` elsewhere. It is written into the central
      directory, so leaving it alone makes the same records produce
      different bytes on Windows than on macOS or Linux. It is pinned to
      Unix beside the mode because the two belong together: `external_attr`
      only reads as a Unix mode when `create_system` says Unix.
    """
    info = zipfile.ZipInfo(name, date_time=_FIXED_DATE)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = _UNIX_CREATE_SYSTEM
    info.external_attr = 0o644 << 16
    return info


def write_archive(archive: ResultArchive, dest: IO[bytes]) -> None:
    """Serialize `archive` into `dest` — deterministic for the same input.

    Entries are written in a fixed order (manifest, readme, methods, then
    arrays in record and output order) so two exports of one selection are
    byte-identical apart from whatever `generated_at` the manifest carries.

    Arrays are STREAMED into their entries, as `write_result_members` does
    for a `.fvp`: an elemental-map stack or a spectrum cube is exactly the
    payload worth exporting, and buffering one whole to hand `writestr` a
    `bytes` would defeat the reason the project writer streams. Hence
    `force_zip64`, since the compressed size is unknown when the entry
    header goes down.

    `dest` is any writable binary file — the CALLER chooses where the
    archive accumulates, which is the half of "bounded memory" this
    function cannot decide for itself. Streaming each array into its entry
    only avoids one array-sized copy; the archive still has to go
    somewhere, so a caller exporting the multi-gigabyte payloads named
    above should pass a spooled or on-disk file rather than an in-memory
    buffer. `routes/results_api.py` does.
    """
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            _entry(MANIFEST_NAME),
            json.dumps(archive.manifest, indent=2).encode("utf-8"),
        )
        zf.writestr(_entry(README_NAME), archive.readme.encode("utf-8"))
        zf.writestr(_entry(METHODS_NAME), archive.methods.encode("utf-8"))
        for record in archive.records:
            for output in record.outputs:
                if output.member is None or output.array is None:
                    continue
                with zf.open(_entry(output.member), "w", force_zip64=True) as entry:
                    np.save(entry, output.array, allow_pickle=False)


def archive_bytes(archive: ResultArchive) -> bytes:
    """The whole archive as one `bytes`.

    A convenience for callers that already hold the payload in memory and
    want the bytes — tests, and anything comparing two archives. It costs
    a full in-memory copy of the archive, so it is NOT what an export
    endpoint should use: see `write_archive` and the spooled file in
    `routes/results_api.py`.
    """
    buf = io.BytesIO()
    write_archive(archive, buf)
    return buf.getvalue()
