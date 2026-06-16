// App title bar: brand, centred doc title, panel toggles (handoff §4
// "Shell"). The prototype's macOS traffic lights were a Claude-Design
// artifact — on Windows the browser/native window owns that chrome,
// so they are intentionally NOT rendered (plan #36).

import { useViewer } from "../../store/viewer";

export default function TitleBar() {
  const activeId = useViewer((s) => s.activeId);
  const name = useViewer((s) =>
    s.activeId ? (s.images[s.activeId]?.name ?? "") : "",
  );
  const toggleLeft = useViewer((s) => s.toggleLeft);
  const toggleRight = useViewer((s) => s.toggleRight);
  const toggleTheme = useViewer((s) => s.toggleTheme);
  const theme = useViewer((s) => s.theme);
  const setShorts = useViewer((s) => s.setShorts);

  const stem = name.replace(/(\.[^.]+)$/, "");
  const ext = name.match(/\.[^.]+$/)?.[0] ?? "";

  return (
    <header className="fvd-titlebar">
      <div className="fvd-brand">
        <span className="fvd-app-icon" />
        <span className="fvd-app-name">FermiViewer</span>
      </div>
      <div className="fvd-doc-title">
        {activeId ? (
          <>
            {stem}
            <span className="ext">{ext}</span>
          </>
        ) : (
          ""
        )}
      </div>
      <div className="fvd-panel-toggles">
        <button
          className="fvd-icon-btn"
          data-tip="Keyboard shortcuts"
          data-tip-key="?"
          onClick={() => setShorts(true)}
        >
          ⌨
        </button>
        <button
          className="fvd-icon-btn"
          data-tip="Toggle theme"
          data-tip-key="⌘⇧L"
          onClick={toggleTheme}
        >
          {theme === "dark" ? "☾" : "☀"}
        </button>
        <button
          className="fvd-icon-btn"
          data-tip="Toggle library"
          data-tip-key="⌘["
          onClick={toggleLeft}
        >
          ◧
        </button>
        <button
          className="fvd-icon-btn"
          data-tip="Toggle inspector"
          data-tip-key="⌘]"
          onClick={toggleRight}
        >
          ◨
        </button>
      </div>
    </header>
  );
}
