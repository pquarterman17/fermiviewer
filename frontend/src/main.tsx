import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { connectLifecycle } from "./lib/lifecycle";
import { useViewer } from "./store/viewer";
import "./theme.css";
import "./theme-web.css";

connectLifecycle();

// dev-only: expose the store for E2E driving / debugging (stripped from prod)
if (import.meta.env.DEV) {
  (window as unknown as { __fvStore: typeof useViewer }).__fvStore = useViewer;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
