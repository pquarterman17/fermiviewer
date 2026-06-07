import { useEffect, useState } from "react";

// Placeholder shell. Handoff Phase 1 (PORT_PLAN item 23) replaces this
// with the real TitleBar/MenuBar/Filmstrip/Stage/Inspector skeleton and
// ports theme.css / theme-web.css verbatim from design/handoff/.
export default function App() {
  const [health, setHealth] = useState<string>("checking backend…");

  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((b) => setHealth(`backend ok · v${b.version}`))
      .catch(() => setHealth("backend offline — run `uv run fv`"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui", padding: "2rem", color: "#ddd", background: "#0e1014", minHeight: "100vh" }}>
      <h1>FermiViewer</h1>
      <p>{health}</p>
    </main>
  );
}
