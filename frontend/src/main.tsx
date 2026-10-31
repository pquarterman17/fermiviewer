import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import AppErrorBoundary from "./components/AppErrorBoundary";
import { connectLifecycle } from "./lib/lifecycle";
import { useScribble } from "./store/scribble";
import { useViewer } from "./store/viewer";
// Global so every chart is styled however its (lazy) chunk arrives; it used
// to ride in with the dock plot, which now loads on the first profile.
import "uplot/dist/uPlot.min.css";
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
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </StrictMode>,
);
