"""Hatchling build hook — bake the built SPA into the wheel.

When `frontend/dist` exists at build time, its contents ship inside the
wheel as `fermiviewer/_spa/`, so a plain `pip install fermiviewer-*.whl`
serves the full app with no Node/npm on the target machine. This is what
makes the offline / air-gapped install path (tools/offline/) work.

When the dist is absent (a backend-only build) the wheel simply omits
it — `server._frontend_dist()` falls back to the repo-layout lookup.

Editable installs are skipped on purpose: in dev the repo's own
frontend/dist is the live copy, and baking a snapshot into the venv
would shadow frontend rebuilds.
"""

from __future__ import annotations

import os
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class SpaBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        if self.target_name != "wheel" or version == "editable":
            return
        dist = os.path.join(self.root, "frontend", "dist")
        if os.path.isfile(os.path.join(dist, "index.html")):
            build_data["force_include"][dist] = "fermiviewer/_spa"
