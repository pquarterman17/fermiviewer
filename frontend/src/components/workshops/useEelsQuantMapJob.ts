import { useState } from "react";

import {
  eelsQuantifyMapAsync,
  runJob,
  type EelsQuantMapResult,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import type { EdgeRow } from "./EelsEdgeEditor";

export function useEelsQuantMapJob({
  activeId,
  edges,
  e0Kv,
  betaMrad,
  method,
}: {
  activeId: string | null;
  edges: EdgeRow[];
  e0Kv: number;
  betaMrad: number;
  method: string;
}) {
  const setStatus = useViewer((state) => state.setStatus);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState("");

  const run = () => {
    if (!activeId || busy) return;
    const clean = edges.filter((edge) => edge.element && edge.z > 0);
    if (clean.length === 0) {
      setStatus("EELS maps: add at least one edge row");
      return;
    }
    setBusy(true);
    setProgress("starting…");
    runJob<EelsQuantMapResult>(
      () => eelsQuantifyMapAsync(
        activeId, clean.map(({ key: _key, ...edge }) => edge),
        e0Kv, betaMrad, method,
      ),
      (fraction, message) =>
        setProgress(`${Math.round(fraction * 100)}% ${message}`),
    )
      .then((result) => {
        useViewer.getState().ingestDerived(result.maps);
        setStatus(
          `EELS composition maps: ${result.elements
            .map((element, index) =>
              `${element} ${result.mean_atomic_percent[index].toFixed(1)}%`)
            .join(" · ")}`,
        );
      })
      .catch((error: Error) => setStatus(`EELS maps: ${error.message}`))
      .finally(() => {
        setBusy(false);
        setProgress("");
      });
  };

  return { busy, progress, run };
}
