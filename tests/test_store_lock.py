"""Cross-process store locking (`fermiviewer.storelock`).

The claim under test is the one the `threading.RLock` these stores used
before could not make: two *processes* sharing one `~/.fermiviewer/`
serialise their read/modify/write transactions instead of losing one
whole. That configuration is reachable — `server.py` floats a second
launch to another port when its 0.5 s health probe misses a sibling that
has bound the port but is still importing numpy — so every test here uses
real subprocesses, not threads. A thread-only lock passes nothing below.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from fermiviewer.storelock import StoreLock


def _run(code: str, **env: str) -> subprocess.Popen[bytes]:
    """Start a child interpreter running ``code`` with the repo importable."""
    child_env = {**os.environ, **env}
    return subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(code)],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _drain(proc: subprocess.Popen[bytes], timeout: float = 120.0) -> None:
    out, err = proc.communicate(timeout=timeout)
    assert proc.returncode == 0, err.decode(errors="replace") or out.decode(errors="replace")


# ── mutual exclusion ──────────────────────────────────────────────────


def test_lock_excludes_another_process(tmp_path: Path) -> None:
    """While a child holds the lock, the parent cannot enter it.

    The child stamps ``in`` on entry and ``out`` on exit; the parent waits
    for ``in``, then acquires. If the acquisition really waited, the file
    already says ``out`` by the time the parent is inside. A thread lock
    lets the parent in immediately and reads ``in``.
    """
    store = tmp_path / "store.json"
    witness = tmp_path / "witness.txt"
    child = _run(
        f"""
        import time
        from pathlib import Path
        from fermiviewer.storelock import StoreLock

        lock = StoreLock(lambda: Path({str(store)!r}))
        witness = Path({str(witness)!r})
        with lock:
            witness.write_text("in")
            time.sleep(3.0)
            witness.write_text("out")
        """
    )
    try:
        deadline = time.monotonic() + 90.0
        while not (witness.exists() and witness.read_text() == "in"):
            assert time.monotonic() < deadline, "child never entered the lock"
            time.sleep(0.01)

        lock = StoreLock(lambda: store)
        with lock:
            assert witness.read_text() == "out", "acquired the lock while another process held it"
    finally:
        _drain(child)


def test_lock_serialises_read_modify_write(tmp_path: Path) -> None:
    """Four processes doing the stores' load/modify/save shape keep all
    four writes.

    Each child sleeps inside the transaction, between load and save, so
    without cross-process exclusion every child loads the same empty file
    and the last `os.replace` wins whole — one entry survives instead of
    four. This is the lost update the `RLock` could not prevent.
    """
    store = tmp_path / "store.json"
    store.write_text("{}")
    children = [
        _run(
            f"""
            import json, time
            from pathlib import Path
            from fermiviewer.storelock import StoreLock

            store = Path({str(store)!r})
            lock = StoreLock(lambda: store)
            with lock:
                data = json.loads(store.read_text())
                time.sleep(0.4)
                data[{f"w{i}"!r}] = {i}
                tmp = store.with_suffix(".tmp{i}")
                tmp.write_text(json.dumps(data))
                tmp.replace(store)
            """
        )
        for i in range(4)
    ]
    for child in children:
        _drain(child)
    data = json.loads(store.read_text())
    assert data == {"w0": 0, "w1": 1, "w2": 2, "w3": 3}


# ── the real stores ───────────────────────────────────────────────────


_STORE_CASES = {
    "profiles": (
        "FV_PROFILES_PATH",
        "profiles.json",
        """
        from fermiviewer.io import profiles_db as db
        lock, load, save = db._LOCK, db._load, db._save
        def put(data, i):
            data["profiles"][f"p{i}"] = {"name": f"p{i}"}
        """,
        lambda raw: sorted(raw["profiles"]),
    ),
    "calibrations": (
        "FV_CALIB_PATH",
        "calibrations.json",
        """
        from fermiviewer.io import calibration_db as db
        lock, load, save = db._LOCK, db._load, db._save
        def put(data, i):
            data[f"p{i}"] = {"name": f"p{i}"}
        """,
        lambda raw: sorted(raw),
    ),
}


@pytest.mark.parametrize("case", sorted(_STORE_CASES))
def test_store_transactions_do_not_lose_updates(case: str, tmp_path: Path) -> None:
    """Same lost-update proof, driven through each store's own `_LOCK`,
    `_load` and `_save` rather than a stand-in lock — so it fails if a
    store is ever reverted to a thread-only lock."""
    env_var, filename, preamble, keys = _STORE_CASES[case]
    store = tmp_path / filename
    children = [
        _run(
            "import time\n" + textwrap.dedent(preamble).strip() + "\n\n" + f"with lock:\n"
            f"    data = load()\n"
            f"    time.sleep(0.4)\n"
            f"    put(data, {i})\n"
            f"    save(data)\n",
            **{env_var: str(store)},
        )
        for i in range(4)
    ]
    for child in children:
        _drain(child)
    assert keys(json.loads(store.read_text())) == ["p0", "p1", "p2", "p3"]


def test_workspace_index_does_not_lose_updates(tmp_path: Path) -> None:
    """The workspace index is the third store with the same shape; it is
    keyed off `FV_CONFIG_DIR` rather than a store-specific override."""
    config = tmp_path / "config"
    children = [
        _run(
            f"""
            import time
            from fermiviewer import workspaces

            with workspaces._LOCK:
                data = workspaces._read_index()
                time.sleep(0.4)
                data["workspaces"][f"w{i}"] = {{"name": f"w{i}", "n_images": 1}}
                workspaces._write_index(data)
            """,
            FV_CONFIG_DIR=str(config),
        )
        for i in range(4)
    ]
    for child in children:
        _drain(child)
    index = json.loads((config / "workspaces" / "index.json").read_text())
    assert sorted(index["workspaces"]) == ["w0", "w1", "w2", "w3"]


# ── behaviour of the lock itself ──────────────────────────────────────


def test_reentrant_within_a_thread(tmp_path: Path) -> None:
    """`import_legacy_calibrations` holds the store lock across a batch
    that re-enters it, so nesting must not self-deadlock."""
    lock = StoreLock(lambda: tmp_path / "store.json")
    with lock:
        with lock:
            assert (tmp_path / "store.json.lock").exists()


def test_follows_a_relocated_store(tmp_path: Path) -> None:
    """The lock file is resolved per acquisition, so a store whose path
    moves between transactions (the env overrides tests use) locks the new
    location, not the old one."""
    current = tmp_path / "a.json"
    lock = StoreLock(lambda: current)
    with lock:
        pass
    assert (tmp_path / "a.json.lock").exists()
    current = tmp_path / "sub" / "b.json"
    with lock:
        pass
    assert (tmp_path / "sub" / "b.json.lock").exists()


def test_degrades_when_the_lock_file_cannot_be_created(tmp_path: Path) -> None:
    """A config dir that cannot hold a lock file must not fail the
    request — the lock falls back to thread-only exclusion.

    The unwritable location is a path whose parent is a regular *file*,
    not a directory mode: the suite runs as root in CI, where mode bits
    are bypassed and a permissions-based version of this test would pass
    without ever reaching the fallback.
    """
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("")
    target = blocker / "store.json"

    lock = StoreLock(lambda: target)
    with lock:  # no exception is the assertion
        assert lock._fd is None, "expected the thread-only fallback"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock path")
def test_degrades_when_the_filesystem_cannot_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A filesystem whose lock call fails with something other than
    'someone else holds it' degrades at once.

    The distinction matters: treating ENOLCK as contention would spin the
    full timeout on *every* transaction, turning an unlockable mount into
    a multi-second stall per save rather than a silent fallback.
    """
    import errno as _errno
    import fcntl

    def enolck(*args: object, **kwargs: object) -> None:
        raise OSError(_errno.ENOLCK, "no locks available")

    monkeypatch.setattr(fcntl, "flock", enolck)
    lock = StoreLock(lambda: tmp_path / "store.json")
    started = time.monotonic()
    with lock:
        assert lock._fd is None
    assert time.monotonic() - started < 1.0, "spun on an unlockable filesystem"


def test_does_not_leak_a_descriptor_when_setup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A lock file that opens but cannot be prepared must not leak its fd.

    The open and the byte-write that follows it were once in one `try`, so
    a failure after the open returned without closing. `_acquire_file`
    runs once per store transaction, so on a full lock filesystem -- the
    exact case it is meant to degrade for -- that leaked one descriptor
    per save until the process ran out of handles.

    The leak is measured rather than asserted structurally: `os.open`
    hands back the lowest free descriptor, so a probe taken before and
    after a run of failed acquisitions returns the same number if every
    fd was closed, and a higher one if they were not.
    """
    import errno as _errno

    def enospc(*args: object, **kwargs: object) -> None:
        raise OSError(_errno.ENOSPC, "no space left on device")

    lock = StoreLock(lambda: tmp_path / "store.json")
    with lock:
        pass  # create the lock file while writes still work

    monkeypatch.setattr(os, "write", enospc)

    def probe() -> int:
        fd = os.open(os.devnull, os.O_RDONLY)
        os.close(fd)
        return fd

    # the file exists but is empty, so every acquisition retries the write
    (tmp_path / "store.json.lock").write_bytes(b"")
    before = probe()
    for _ in range(20):
        with lock:
            assert lock._fd is None, "expected the thread-only fallback"
    after = probe()
    assert after == before, (
        f"leaked descriptors: probe moved {before} -> {after} over 20 "
        "failed acquisitions"
    )


def test_releases_on_an_exception(tmp_path: Path) -> None:
    """A transaction that raises still releases the file lock, or the
    next request in the same process would block for the full timeout."""
    lock = StoreLock(lambda: tmp_path / "store.json")
    with pytest.raises(RuntimeError):
        with lock:
            raise RuntimeError("boom")
    child = _run(
        f"""
        from pathlib import Path
        from fermiviewer.storelock import StoreLock
        lock = StoreLock(lambda: Path({str(tmp_path / "store.json")!r}))
        with lock:
            pass
        """
    )
    _drain(child, timeout=120.0)
