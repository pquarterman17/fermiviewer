// Keeps the 4D dataset picker's list in sync with the server (PLAN_4DSTEM
// #14: "a dataset closed server-side only self-heals on next select/
// remount"). Refetches on mount, and again whenever the workshop's tab
// regains focus/visibility — the tab may have been hidden while a dataset
// was closed elsewhere (another browser tab, a server restart, a script
// via the CLI/API). Per-id 404s while browsing (store/fourd.ts's
// `isStaleDataset` branches) already self-heal on their own; this hook
// covers the "nothing happened yet to trigger a refetch" gap.
//
// Deliberately event-driven, NOT polling: for a local single-user app, a
// hidden/visible transition and a window-focus event cover every realistic
// staleness case without a recurring timer to reason about. If polling is
// ever needed, add ONE `setInterval` here (>=10s, gated on
// `document.visibilityState === "visible"`) — this hook is the single,
// trivially-removable place it would go.

import { useEffect } from "react";

import { useFourD } from "../../../store/fourd";

export function useFourDDatasetRefresh(): void {
  const fetchDatasets = useFourD((s) => s.fetchDatasets);

  useEffect(() => {
    void fetchDatasets();
    const onFocusOrVisible = () => {
      if (document.visibilityState === "visible") void fetchDatasets();
    };
    document.addEventListener("visibilitychange", onFocusOrVisible);
    window.addEventListener("focus", onFocusOrVisible);
    return () => {
      document.removeEventListener("visibilitychange", onFocusOrVisible);
      window.removeEventListener("focus", onFocusOrVisible);
    };
  }, [fetchDatasets]);
}
