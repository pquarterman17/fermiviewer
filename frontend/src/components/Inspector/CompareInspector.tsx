// Compare inspector (handoff §4): mode segmented control, slot list,
// exit. Linked zoom/pan is inherent (one shared transform in the stage).
// Audit #15 additions: flicker rate + A/B index pair + Tab hint.

import { useViewer, type CompareMode } from "../../store/viewer";

// stable empty fallback — a fresh [] in the selector breaks referential
// equality and re-renders every store tick (zustand snapshot rule)
const EMPTY_IDS: string[] = [];

const MODES: { key: CompareMode; label: string }[] = [
  { key: "split", label: "Split" },
  { key: "flicker", label: "Flicker" },
  { key: "subtract", label: "Subtract" },
  { key: "sidebyside", label: "Side-by-side" },
];

/** Grid shapes offered for the N-pane side-by-side compare. */
const GRID_SHAPES: { rows: number; cols: number; label: string }[] = [
  { rows: 1, cols: 2, label: "1×2" },
  { rows: 1, cols: 3, label: "1×3" },
  { rows: 2, cols: 2, label: "2×2" },
  { rows: 2, cols: 3, label: "2×3" },
];

export default function CompareInspector() {
  const compareSet = useViewer((s) => s.compareSet ?? EMPTY_IDS);
  const compareMode = useViewer((s) => s.compareMode);
  const compareFlickerMs = useViewer((s) => s.compareFlickerMs);
  const compareAB = useViewer((s) => s.compareAB);
  const setCompareMode = useViewer((s) => s.setCompareMode);
  const setCompareFlickerMs = useViewer((s) => s.setCompareFlickerMs);
  const setCompareAB = useViewer((s) => s.setCompareAB);
  const exitCompare = useViewer((s) => s.exitCompare);
  const images = useViewer((s) => s.images);
  const startCompare = useViewer((s) => s.startCompare);
  const sbsPanes = useViewer((s) => s.sbsPanes);
  const sbsRows = useViewer((s) => s.sbsRows);
  const sbsCols = useViewer((s) => s.sbsCols);
  const sbsActive = useViewer((s) => s.sbsActive);
  const setActivePane = useViewer((s) => s.setActivePane);
  const setGrid = useViewer((s) => s.setGrid);
  const sbsLinked = useViewer((s) => s.sbsLinked);
  const setSbsLinked = useViewer((s) => s.setSbsLinked);
  const sideBySide = compareMode === "sidebyside";

  const removeSlot = (id: string) => {
    const rest = compareSet.filter((c) => c !== id);
    if (rest.length >= 2) startCompare(rest);
    else exitCompare();
  };

  // Flicker rate in Hz for display; underlying store holds ms.
  const flickerHz = (1000 / compareFlickerMs).toFixed(1);

  return (
    <aside className="fvd-inspector">
      <div className="fvd-card">
        <h3>Compare</h3>
        <div className="fvd-seg fvd-seg-wide">
          {MODES.map((m) => (
            <button
              key={m.key}
              className={`fvd-seg-btn${compareMode === m.key ? " active" : ""}`}
              onClick={() => setCompareMode(m.key)}
              title={`Show the compared images as ${m.label}`}
            >
              {m.label}
            </button>
          ))}
        </div>

        {/* Side-by-side controls: link toggle + focused-side picker + hint */}
        {sideBySide && (
          <>
            <div className="fvd-meta-row" style={{ marginTop: 6 }}>
              <span className="k">Zoom</span>
              <button
                className={`fvd-seg-btn${sbsLinked ? " active" : ""}`}
                title="Link the zoom level across both panes (each pane still pans on its own)"
                onClick={() => setSbsLinked(!sbsLinked)}
              >
                {sbsLinked ? "🔗 Linked" : "Independent"}
              </button>
            </div>
            <div className="fvd-meta-row" style={{ marginTop: 6 }}>
              <span className="k">Grid</span>
              <div className="fvd-seg">
                {GRID_SHAPES.map((g) => (
                  <button
                    key={g.label}
                    className={`fvd-seg-btn${
                      sbsRows === g.rows && sbsCols === g.cols ? " active" : ""
                    }`}
                    title={`${g.rows * g.cols} panes`}
                    onClick={() => setGrid(g.rows, g.cols)}
                  >
                    {g.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="fvd-meta-row" style={{ marginTop: 6 }}>
              <span className="k">Focus pane</span>
              <div className="fvd-seg" style={{ flexWrap: "wrap" }}>
                {sbsPanes.map((_, i) => (
                  <button
                    key={i}
                    className={`fvd-seg-btn${sbsActive === i ? " active" : ""}`}
                    onClick={() => setActivePane(i)}
                    title={`Focus pane ${i + 1} (arrow keys step, Tab cycles)`}
                  >
                    {i + 1}
                  </button>
                ))}
              </div>
            </div>
            <div
              className="fvd-text-faint"
              style={{ fontSize: 11, marginTop: 6 }}
            >
              Click a pane to focus it (cyan border); ◀ ▶ or ←/→ step it within
              its bound group, Tab cycles panes. The others stay frozen. With
              zoom linked, zooming one pane matches the rest. Bind a named group
              to a pane from its top-left dropdown.
            </div>
          </>
        )}

        {/* Flicker controls (audit #15) — visible in flicker mode only */}
        {compareMode === "flicker" && (
          <div className="fvd-meta-row" style={{ marginTop: 6 }}>
            <span className="k" style={{ whiteSpace: "nowrap" }}>
              Rate
            </span>
            <input
              type="range"
              min={100}
              max={2000}
              step={50}
              value={compareFlickerMs}
              title={`Flicker interval: ${compareFlickerMs} ms (${flickerHz} Hz)`}
              onChange={(e) => setCompareFlickerMs(Number(e.target.value))}
              style={{ flex: 1 }}
            />
            <span className="v" style={{ minWidth: 52, textAlign: "right" }}>
              {flickerHz} Hz
            </span>
          </div>
        )}

        {!sideBySide && (
          <div className="fvd-compare-slots">
            {compareSet.map((id, i) => (
              <div key={id} className="fvd-measure-row">
                <span className="glyph">{String.fromCharCode(65 + i)}</span>
                <span className="name" title={images[id]?.name}>
                  {images[id]?.name ?? id}
                </span>
                <button
                  className="fvd-icon-btn"
                  title="Remove from compare"
                  onClick={() => removeSlot(id)}
                >
                  ✕
                </button>
              </div>
            ))}
          </div>
        )}

        {/* A/B pair picker (audit #15): explicit two-slot flicker pair.
            Only shown when ≥3 images are being compared; otherwise the
            full-set cycle is the same as an A/B pick. */}
        {compareMode === "flicker" && compareSet.length >= 3 && (
          <div style={{ marginTop: 6 }}>
            <div className="fvd-meta-row">
              <span className="k">A/B pair</span>
              <button
                className={`fvd-seg-btn${compareAB === null ? " active" : ""}`}
                title="Cycle all images"
                onClick={() => setCompareAB(null)}
              >
                All
              </button>
            </div>
            <div className="fvd-zscale-row" style={{ gap: 4, marginTop: 4 }}>
              {(["A", "B"] as const).map((slot, si) => (
                <select
                  key={slot}
                  value={compareAB?.[si] ?? si}
                  title={`Slot ${slot}`}
                  onChange={(e) => {
                    const idx = Number(e.target.value);
                    const other = compareAB?.[1 - si] ?? (si === 0 ? 1 : 0);
                    const pair: [number, number] =
                      si === 0 ? [idx, other] : [other, idx];
                    setCompareAB(pair);
                  }}
                >
                  {compareSet.map((cid, ci) => (
                    <option key={cid} value={ci}>
                      {slot}: {images[cid]?.name ?? cid}
                    </option>
                  ))}
                </select>
              ))}
            </div>
          </div>
        )}

        {compareMode === "flicker" && (
          <div
            className="fvd-text-faint"
            style={{ fontSize: 11, marginTop: 4 }}
          >
            Tab advances the visible panel
          </div>
        )}

        <div className="fvd-btn-row">
          <button
            className="fvd-btn"
            onClick={exitCompare}
            title="Exit compare and return to single-image view (Esc)"
          >
            Exit compare
          </button>
        </div>
      </div>
    </aside>
  );
}
