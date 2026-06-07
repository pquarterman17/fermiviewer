// Native-style window chrome: traffic lights, centred doc title,
// panel toggles (handoff §4 "Shell"). Lights are decorative until Tauri.

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
        <div className="fvd-traffic">
          <span className="r" />
          <span className="y" />
          <span className="g" />
        </div>
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
          title="Keyboard shortcuts  ?"
          onClick={() => setShorts(true)}
        >
          ⌨
        </button>
        <button
          className="fvd-icon-btn"
          title="Toggle theme  ⌘⇧L"
          onClick={toggleTheme}
        >
          {theme === "dark" ? "☾" : "☀"}
        </button>
        <button
          className="fvd-icon-btn"
          title="Toggle library  ⌘["
          onClick={toggleLeft}
        >
          ◧
        </button>
        <button
          className="fvd-icon-btn"
          title="Toggle inspector  ⌘]"
          onClick={toggleRight}
        >
          ◨
        </button>
      </div>
    </header>
  );
}
