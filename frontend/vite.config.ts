/// <reference types="vitest/config" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Dev server proxies /api to the FastAPI backend (uv run fv → :8000)
export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: {
        codeSplitting: {
          // React changes far less often than the app, so keep it in its own
          // long-lived chunk instead of re-shipping it inside every entry
          // build. Only the React runtime and its store binding: chart
          // libraries (uPlot) stay with the lazy chunks that use them, off
          // the first-paint path.
          groups: [
            {
              name: "react",
              test: /node_modules[\\/](react|react-dom|scheduler|zustand)[\\/]/,
            },
          ],
        },
      },
    },
  },
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        ws: true, // lifecycle websocket
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
