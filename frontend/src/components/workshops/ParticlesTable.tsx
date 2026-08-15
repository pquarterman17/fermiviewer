// Particle table for ParticlesMode's "find similar" action
// (SHAPE_ANALYSIS_PLAN.md Wave 2 — GUI wiring, item #4). Split out of
// ParticlesMode.tsx to keep that file under the repo's line cap.
//
// Two render modes, chosen by whether `similarity` is set:
//  - normal: id/area/circ./AR/class + a per-row "≈" action that kicks off
//    an EFD-similarity query against that row.
//  - similarity: the same rows plus a DIMENSIONLESS distance column
//    (SHAPE_ANALYSIS_PLAN Wave 2 — normalized EFD space, never a unit),
//    sorted ascending (the reference lands first at ≈0). Skipped
//    particles (contour too small/absent for the harmonic count) stay
//    visible with "—" and their reason on hover, never dropped from the
//    table silently.
//
// This is a SEPARATE table from the ResultsWindow push ParticlesMode
// already does on Count — that one is the generic CSV/JSON export
// surface (lib/api/imaging.ts's `ParticleRow[]` flattened to primitives,
// no room for a per-row button or a hover reason). This table is the
// interactive one; ResultsWindow is untouched (owned outside this wave's
// file partition).

import type {
  EfdSimilarityRanked,
  EfdSimilaritySkipped,
  ParticleRow,
} from "../../lib/api";

export interface SimilarityState {
  refId: number;
  ranked: EfdSimilarityRanked[];
  skipped: EfdSimilaritySkipped[];
}

interface Props {
  particles: ParticleRow[];
  similarity: SimilarityState | null;
  /** id of the row whose find-similar request is in flight, if any */
  busyId: number | null;
  onFindSimilar: (refId: number) => void;
  onClear: () => void;
}

function fmtAr(ar: number | null): string {
  return ar == null ? "—" : ar.toFixed(2);
}

/** 3 significant figures, per SHAPE_ANALYSIS_PLAN Wave 2's distance-column
 *  spec. Distances are dimensionless (normalized EFD space) — this string
 *  never carries a unit suffix. */
function fmtDistance(d: number): string {
  return d.toPrecision(3);
}

export default function ParticlesTable({
  particles,
  similarity,
  busyId,
  onFindSimilar,
  onClear,
}: Props) {
  if (particles.length === 0) return null;

  if (!similarity) {
    return (
      <table className="fvd-ws-table">
        <thead>
          <tr>
            <th>id</th>
            <th>area</th>
            <th>circ.</th>
            <th>AR</th>
            <th>class</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          {particles.map((p) => (
            <tr key={p.id}>
              <td>{p.id}</td>
              <td>{p.area}</td>
              <td>{p.circularity.toFixed(2)}</td>
              <td>{fmtAr(p.aspect_ratio)}</td>
              <td>{p.shape_class}</td>
              <td>
                <button
                  className="fvd-icon-btn"
                  title="Find particles with a similar shape (EFD contour similarity)"
                  disabled={busyId != null}
                  onClick={() => onFindSimilar(p.id)}
                >
                  {busyId === p.id ? "…" : "≈"}
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    );
  }

  const byId = new Map(particles.map((p) => [p.id, p]));
  type Row =
    | { kind: "ranked"; particle: ParticleRow; distance: number }
    | { kind: "skipped"; particle: ParticleRow; reason: string };

  const rankedRows: Row[] = similarity.ranked
    .slice()
    .sort((a, b) => a.distance - b.distance)
    .flatMap((r) => {
      const particle = byId.get(r.id);
      return particle ? [{ kind: "ranked" as const, particle, distance: r.distance }] : [];
    });
  const skippedRows: Row[] = similarity.skipped.flatMap((s) => {
    const particle = byId.get(s.id);
    return particle ? [{ kind: "skipped" as const, particle, reason: s.reason }] : [];
  });
  const rows = [...rankedRows, ...skippedRows];

  return (
    <>
      <div className="fvd-ws-row" style={{ alignItems: "center" }}>
        <span className="fvd-ws-note" style={{ margin: 0 }}>
          similar to #{similarity.refId} — ranked {similarity.ranked.length} ·
          skipped {similarity.skipped.length}
        </span>
        <span style={{ flex: 1 }} />
        <button
          className="fvd-btn"
          title="Exit similarity ranking and restore the normal particle table"
          onClick={onClear}
        >
          Clear
        </button>
      </div>
      <table className="fvd-ws-table">
        <thead>
          <tr>
            <th>id</th>
            <th>distance</th>
            <th>area</th>
            <th>circ.</th>
            <th>AR</th>
            <th>class</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.particle.id}>
              <td>{row.particle.id}</td>
              <td title={row.kind === "skipped" ? row.reason : undefined}>
                {row.kind === "ranked" ? fmtDistance(row.distance) : "—"}
              </td>
              <td>{row.particle.area}</td>
              <td>{row.particle.circularity.toFixed(2)}</td>
              <td>{fmtAr(row.particle.aspect_ratio)}</td>
              <td>{row.particle.shape_class}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}
