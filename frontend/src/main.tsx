import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { connectLifecycle } from "./lib/lifecycle";
import { useScribble } from "./store/scribble";
import { useViewer } from "./store/viewer";
import "./theme.css";
import "./theme-web.css";

connectLifecycle();

// dev-only: expose the stores for E2E driving / debugging (stripped from prod)
if (import.meta.env.DEV) {
  const w = window as unknown as {
    __fvStore: typeof useViewer;
    __fvScribble: typeof useScribble;
  };
  w.__fvStore = useViewer;
  w.__fvScribble = useScribble;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
