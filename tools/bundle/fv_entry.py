"""PyInstaller entry point for the self-contained server sidecar.

Equivalent to `python -m fermiviewer` — kept as a separate script so
the spec has a stable target and the package itself stays untouched.
"""

from fermiviewer.server import main

if __name__ == "__main__":
    main()
