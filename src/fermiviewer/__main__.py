"""`python -m fermiviewer` — used by the Tauri shell to spawn the
server as a directly-killable process (no launcher-exe indirection)."""

from fermiviewer.server import main

if __name__ == "__main__":
    main()
