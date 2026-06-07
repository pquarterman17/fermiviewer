// Compare inspector (handoff §4): mode segmented control, slot list,
// exit. Linked zoom/pan is inherent (one shared transform in the stage).

import { useViewer, type CompareMode } from "../../store/viewer";

const MODES: { key: CompareMode; label: string }[] = [
  { key: "split", label: "Split" },
  { key: "flicker", label: "Flicker" },
  { key: "subtract", label: "Subtract" },
];

export default function CompareInspector() {
  const compareSet = useViewer((s) => s.compareSet) ?? [];
  const compareMode = useViewer((s) => s.compareMode);
  const setCompareMode = useViewer((s) => s.setCompareMode);
  const exitCompare = useViewer((s) => s.exitCompare);
  const images = useViewer((s) => s.images);
  const startCompare = useViewer((s) => s.startCompare);

  const removeSlot = (id: string) => {
    const rest = compareSet.filter((c) => c !== id);
    if (rest.length >= 2) startCompare(rest);
    else exitCompare();
  };

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
        <div className="fvd-btn-row">
          <button className="fvd-btn" onClick={exitCompare}>
            Exit compare
          </button>
        </div>
      </div>
    </aside>
  );
}
