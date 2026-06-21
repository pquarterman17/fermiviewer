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
  const sbsActive = useViewer((s) => s.sbsActive);
  const setSbsActive = useViewer((s) => s.setSbsActive);
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
              <span className="k">Scroll side</span>
              <div className="fvd-seg">
                {(["L", "R"] as const).map((p) => (
                  <button
                    key={p}
                    className={`fvd-seg-btn${sbsActive === p ? " active" : ""}`}
                    onClick={() => setSbsActive(p)}
                  >
                    {p === "L" ? "Left" : "Right"}
                  </button>
                ))}
              </div>
            </div>
            <div className="fvd-text-faint" style={{ fontSize: 11, marginTop: 6 }}>
              Click a side to focus it (cyan border); ◀ ▶ or ←/→ scroll it,
              Tab switches sides. The other side stays frozen. With zoom
              linked, zooming one pane matches the other's magnification.
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
          <div className="fvd-text-faint" style={{ fontSize: 11, marginTop: 4 }}>
            Tab advances the visible panel
          </div>
        )}

        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={exitCompare}>
            Exit compare
          </button>
        </div>
      </div>
    </aside>
  );
}
