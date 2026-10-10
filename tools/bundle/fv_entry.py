"""PyInstaller entry point for the self-contained server sidecar.

Equivalent to `python -m fermiviewer` — kept as a separate script so
the spec has a stable target and the package itself stays untouched.
"""

import multiprocessing

from fermiviewer.server import main

if __name__ == "__main__":
    # a frozen executable must hand spawned worker processes (the force-map
    # pool, calc/afm_force_batch.py) to multiprocessing instead of starting
    # another server
    multiprocessing.freeze_support()
    main()
