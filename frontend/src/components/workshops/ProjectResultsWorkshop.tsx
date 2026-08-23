import { useMemo, useState } from "react";

import type { PersistedResultRecord } from "../../lib/api";
import { useViewer } from "../../store/viewer";
import PersistedResultCard from "../results/PersistedResultCard";

type Scope = "all" | "active";

function createdAt(result: PersistedResultRecord): number {
  // A record written by another tool can legally carry a non-ISO timestamp
  // (the card already renders those as "Unknown date"); NaN in a comparator
  // would make the whole sort order arbitrary, so pin unparseable to 0.
  const parsed = Date.parse(result.created_at);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function newestFirst(a: PersistedResultRecord, b: PersistedResultRecord): number {
  return createdAt(b) - createdAt(a);
}

function involvesImage(result: PersistedResultRecord, imageId: string): boolean {
  // A result is "about" the active image whether that image was its input
  // or its product — a user inspecting an element map expects to find the
  // quantification that produced it.
  return Boolean(
    result.source_ids?.includes(imageId) || result.derived_ids?.includes(imageId),
  );
}

export default function ProjectResultsWorkshop() {
  const results = useViewer((s) => s.persistedResults);
  const images = useViewer((s) => s.images);
  const unavailable = useViewer((s) => s.unavailable);
  const activeId = useViewer((s) => s.activeId);
  const setActive = useViewer((s) => s.setActive);
  const [scope, setScope] = useState<Scope>("all");

  const visible = useMemo(() => {
    const filtered = scope === "active" && activeId
      ? results.filter((result) => involvesImage(result, activeId))
      : results;
    return [...filtered].sort(newestFirst);
  }, [activeId, results, scope]);

  return (
    <section className="fvd-project-results" aria-label="Saved analysis results">
      <div className="fvd-project-results-intro">
        <div>
          <div className="fvd-project-results-kicker">PROJECT RECORD</div>
          <h2>Results &amp; Methods</h2>
          <p>Scientific results saved with this project, including the inputs, settings, calibration and review notes that give each number context.</p>
        </div>
        <div className="fvd-project-results-count" aria-label={`${results.length} saved results`}>
          <strong>{results.length}</strong>
          <span>saved</span>
        </div>
      </div>

      {results.length > 0 && (
        <div className="fvd-project-results-toolbar" aria-label="Result filters">
          <div className="fvd-seg">
            <button className={`fvd-seg-btn${scope === "all" ? " active" : ""}`} aria-pressed={scope === "all"} onClick={() => setScope("all")}>All results</button>
            <button className={`fvd-seg-btn${scope === "active" ? " active" : ""}`} aria-pressed={scope === "active"} disabled={!activeId} onClick={() => setScope("active")}>Active image</button>
          </div>
          <span>{visible.length} shown</span>
        </div>
      )}

      {visible.length === 0 ? (
        <div className="fvd-project-results-empty">
          <div className="symbol" aria-hidden="true">◇</div>
          <strong>{results.length === 0 ? "No saved results yet" : "No results for the active image"}</strong>
          <span>{results.length === 0 ? "Result capture arrives in roadmap item 1C. Existing project records will appear here automatically." : "Switch back to All results or select one of this result’s source images."}</span>
        </div>
      ) : (
        <div className="fvd-project-result-list">
          {visible.map((result) => {
            const sources = (result.source_ids ?? []).map((id) => ({
              id,
              name: images[id]?.name ?? unavailable[id]?.name ?? id,
              available: id in images,
            }));
            return (
              <PersistedResultCard
                key={result.id}
                result={result}
                sources={sources}
                onSelectSource={(id) => setActive(id)}
              />
            );
          })}
        </div>
      )}
    </section>
  );
}
