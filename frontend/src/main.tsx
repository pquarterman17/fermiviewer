import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { connectLifecycle } from "./lib/lifecycle";
import "./theme.css";
import "./theme-web.css";

connectLifecycle();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
