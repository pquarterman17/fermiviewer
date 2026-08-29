import { useEffect, useMemo, useState } from "react";

import type { PersistedResultRecord } from "../../lib/api";
import { openPersistedResult, refreshPersistedResults, rerunPersistedResult } from "../../lib/persistedResultActions";
import { useViewer } from "../../store/viewer";
import PersistedResultCard from "../results/PersistedResultCard";
import ResultsComparePanel from "../results/ResultsComparePanel";

type Scope = "all" | "active";
type GroupBy = "time" | "sample" | "source" | "analysis";
type ResultAction = "reopen" | "rerun" | "duplicate";
type WorkspaceView = "browse" | "compare";

const timeOf = (result: PersistedResultRecord): number => {
  const parsed = Date.parse(result.created_at);
  return Number.isNaN(parsed) ? 0 : parsed;
};
const involvesImage = (result: PersistedResultRecord, imageId: string): boolean =>
  Boolean(result.source_ids?.includes(imageId) || result.derived_ids?.includes(imageId));
const analysisLabel = (analysis: string): string => analysis.split(/[._-]+/)
  .map((part) => part.charAt(0).toUpperCase() + part.slice(1)).join(" ");

export default function ProjectResultsWorkshop() {
  const results = useViewer((s) => s.persistedResults);
  const images = useViewer((s) => s.images);
  const unavailable = useViewer((s) => s.unavailable);
  const groups = useViewer((s) => s.imageGroups);
  const activeId = useViewer((s) => s.activeId);
  const setActive = useViewer((s) => s.setActive);
  const setStatus = useViewer((s) => s.setStatus);
  const [scope, setScope] = useState<Scope>("all");
  const [query, setQuery] = useState("");
  const [analysis, setAnalysis] = useState("all");
  const [status, setResultStatus] = useState("all");
  const [groupBy, setGroupBy] = useState<GroupBy>("time");
  const [view, setView] = useState<WorkspaceView>("browse");
  const [busy, setBusy] = useState<{ id: string; action: ResultAction } | null>(null);
  const nameOf = (id: string): string => images[id]?.name ?? unavailable[id]?.name ?? id;
  const analyses = useMemo(() => [...new Set(results.map((r) => r.analysis))].sort(), [results]);

  useEffect(() => {
    // The server owns persisted records. Refreshing on open also catches a
    // capture made in another workshop while this lazy window was closed.
    void refreshPersistedResults().catch(() => undefined);
  }, []);

  const visible = useMemo(() => {
    const q = query.trim().toLocaleLowerCase();
    return results.filter((result) => {
      if (scope === "active" && activeId && !involvesImage(result, activeId)) return false;
      if (analysis !== "all" && result.analysis !== analysis) return false;
      if (status !== "all" && result.status !== status) return false;
      if (!q) return true;
      return [result.label, result.analysis, ...(result.source_ids ?? []).map(nameOf),
        ...(result.derived_ids ?? []).map(nameOf)].filter(Boolean).join(" ").toLocaleLowerCase().includes(q);
    }).sort((a, b) => timeOf(b) - timeOf(a));
  // nameOf reads the image dictionaries already listed here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId, analysis, images, query, results, scope, status, unavailable]);

  const sections = useMemo(() => {
    const headingOf = (result: PersistedResultRecord): string => {
      const sourceId = result.source_ids?.[0];
      if (groupBy === "analysis") return analysisLabel(result.analysis);
      if (groupBy === "source") return sourceId ? nameOf(sourceId) : "No source";
      if (groupBy === "sample") {
        const membership = groups.filter((group) => sourceId && group.ids.includes(sourceId));
        return membership.at(-1)?.name ?? "Ungrouped";
      }
      const date = new Date(result.created_at);
      if (Number.isNaN(date.valueOf())) return "Unknown date";
      if (date.toDateString() === new Date().toDateString()) return "Today";
      return new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(date);
    };
    const map = new Map<string, PersistedResultRecord[]>();
    for (const result of visible) {
      const heading = headingOf(result);
      map.set(heading, [...(map.get(heading) ?? []), result]);
    }
    return [...map.entries()];
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupBy, groups, images, unavailable, visible]);

  const act = async (result: PersistedResultRecord, action: ResultAction) => {
    setBusy({ id: result.id, action });
    try {
      if (action === "rerun") {
        await rerunPersistedResult(result);
        setStatus(`${result.label || analysisLabel(result.analysis)} rerun and saved`);
      } else {
        openPersistedResult(result, action);
        setStatus(action === "reopen" ? "Saved result reopened" : "Editable copy opened with saved settings");
      }
    } catch (error) {
      setStatus(`result: ${error instanceof Error ? error.message : String(error)}`);
    } finally {
      setBusy(null);
    }
  };

  return <section className="fvd-project-results" aria-label="Saved analysis results">
    <div className="fvd-project-results-intro">
      <div><div className="fvd-project-results-kicker">PROJECT RECORD</div><h2>Results &amp; Methods</h2>
        <p>Find, inspect and reproduce saved analyses without losing their source, settings or calibration context.</p></div>
      <div className="fvd-project-results-count" aria-label={`${results.length} saved results`}><strong>{results.length}</strong><span>saved</span></div>
    </div>
    {results.length > 0 && <nav className="fvd-results-view-nav" aria-label="Results workspace views">
      <button className={view === "browse" ? "active" : ""} aria-current={view === "browse" ? "page" : undefined}
        onClick={() => setView("browse")}><span>Browse</span><small>Inspect &amp; reproduce</small></button>
      <button className={view === "compare" ? "active" : ""} aria-current={view === "compare" ? "page" : undefined}
        onClick={() => setView("compare")}><span>Compare</span><small>Outputs &amp; calibration</small></button>
    </nav>}
    {view === "compare" && results.length > 0 ? <ResultsComparePanel results={results} nameOf={nameOf} /> : <>
    {results.length > 0 && <div className="fvd-project-results-toolbar" aria-label="Result filters">
      <div className="fvd-results-filter-row"><div className="fvd-seg">
        <button className={`fvd-seg-btn${scope === "all" ? " active" : ""}`} aria-pressed={scope === "all"} onClick={() => setScope("all")}>All</button>
        <button className={`fvd-seg-btn${scope === "active" ? " active" : ""}`} aria-pressed={scope === "active"} disabled={!activeId} onClick={() => setScope("active")}>Active image</button>
      </div><input className="fvd-results-search" aria-label="Search saved results" value={query} placeholder="Search results…" onChange={(e) => setQuery(e.target.value)} /></div>
      <div className="fvd-results-filter-row">
        <label>Type<select aria-label="Analysis type" value={analysis} onChange={(e) => setAnalysis(e.target.value)}><option value="all">All analyses</option>{analyses.map((value) => <option key={value} value={value}>{analysisLabel(value)}</option>)}</select></label>
        <label>Status<select aria-label="Result status" value={status} onChange={(e) => setResultStatus(e.target.value)}><option value="all">Any status</option><option value="completed">Complete</option><option value="failed">Failed</option><option value="cancelled">Cancelled</option></select></label>
        <label>Group<select aria-label="Group results by" value={groupBy} onChange={(e) => setGroupBy(e.target.value as GroupBy)}><option value="time">Time</option><option value="sample">Sample</option><option value="source">Source</option><option value="analysis">Analysis</option></select></label>
        <span className="fvd-results-shown">{visible.length} shown</span>
      </div>
    </div>}
    {visible.length === 0 ? <div className="fvd-project-results-empty"><div className="symbol" aria-hidden="true">◇</div>
      <strong>{results.length === 0 ? "No saved results yet" : "No results match these filters"}</strong>
      <span>{results.length === 0 ? "Run a supported analysis and use Save result to keep a reproducible project record. Saved results reappear here when the project is reopened." : "Clear the search or broaden the type, status or image filter."}</span></div>
      : <div className="fvd-project-result-list">{sections.map(([heading, records], sectionIndex) => {
        const headingId = `result-group-${groupBy}-${sectionIndex}`;
        return <section className="fvd-result-group" key={heading} aria-labelledby={headingId}>
          <header><h3 id={headingId}>{heading}</h3><span>{records.length}</span></header>
          {records.map((result) => <PersistedResultCard key={result.id} result={result}
            sources={(result.source_ids ?? []).map((id) => ({ id, name: nameOf(id), available: id in images }))}
            derived={(result.derived_ids ?? []).map((id) => ({ id, name: nameOf(id), available: id in images }))}
            onSelectSource={setActive} onAction={(action) => void act(result, action)}
            busyAction={busy?.id === result.id ? busy.action : null} />)}
        </section>;
      })}</div>}
    </>}
  </section>;
}
