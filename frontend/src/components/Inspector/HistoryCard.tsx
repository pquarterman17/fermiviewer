// Non-destructive edit-history card (design WS4d). Lists every display
// step applied to the active image (Opened → Colormap → Auto contrast →
// Gamma …); the current step is highlighted, click any other to scrub the
// display back (or forward) to that point. Pure display state — reverting
// never touches pixels.

import { useViewer, type HistoryStep } from "../../store/viewer";
import Card from "./Card";

// stable empty snapshot (Zustand #185 — never return a fresh [])
const NO_STEPS: HistoryStep[] = [];

export default function HistoryCard() {
  const activeId = useViewer((s) => s.activeId);
  const steps = useViewer((s) =>
    s.activeId ? (s.history[s.activeId] ?? NO_STEPS) : NO_STEPS,
  );
  const at = useViewer((s) => {
    if (!s.activeId) return -1;
    const h = s.history[s.activeId];
    return s.historyAt[s.activeId] ?? (h ? h.length - 1 : -1);
  });
  const revert = useViewer((s) => s.revertHistory);

  if (!activeId) return null;

  return (
    <Card title="History" count={steps.length} defaultOpen={false}>
      {steps.length === 0 ? (
        <div className="fvd-meta-row">
          <span className="k">No steps yet</span>
        </div>
      ) : (
        <ol className="fvd-history">
          {steps.map((st, i) => (
            <li
              key={st.id}
              className={`fvd-history-step${i === at ? " current" : ""}${
                i > at ? " ahead" : ""
              }`}
              title={
                i === at
                  ? "Current state"
                  : i < at
                    ? "Revert to this step"
                    : "Step forward to this step"
              }
              onClick={() => {
                if (i !== at) revert(activeId, i);
              }}
            >
              <span className="dot" />
              <span className="lbl">{st.label}</span>
              {i === at && <span className="now">now</span>}
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}
