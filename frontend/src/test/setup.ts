// Vitest global setup: jest-dom matchers + clean storage per test.

import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach } from "vitest";
import { cleanup } from "@testing-library/react";

// Node ≥26 + vitest 3.2 jsdom regression: window.localStorage /
// sessionStorage aren't populated onto the global (works under Node 22,
// which CI uses, and standalone jsdom). Polyfill a minimal in-memory Web
// Storage when absent so the suite runs on any local Node. A pure no-op
// where the environment already provides Storage (e.g. CI's Node 22).
class MemoryStorage {
  private m = new Map<string, string>();
  get length(): number {
    return this.m.size;
  }
  clear(): void {
    this.m.clear();
  }
  getItem(k: string): string | null {
    return this.m.has(k) ? (this.m.get(k) as string) : null;
  }
  key(i: number): string | null {
    return Array.from(this.m.keys())[i] ?? null;
  }
  removeItem(k: string): void {
    this.m.delete(k);
  }
  setItem(k: string, v: string): void {
    this.m.set(k, String(v));
  }
}

function ensureStorage(name: "localStorage" | "sessionStorage"): void {
  if (typeof globalThis[name] !== "undefined") return;
  const store = new MemoryStorage() as unknown as Storage;
  Object.defineProperty(globalThis, name, { value: store, configurable: true });
  const win = globalThis.window as (Window & typeof globalThis) | undefined;
  if (win && typeof win[name] === "undefined") {
    Object.defineProperty(win, name, { value: store, configurable: true });
  }
}

ensureStorage("localStorage");
ensureStorage("sessionStorage");

// jsdom has no matchMedia; uPlot reads it at module import (setPxRatio) so any
// test importing a chart-bearing module needs it defined before that import.
if (typeof globalThis.matchMedia === "undefined") {
  Object.defineProperty(globalThis, "matchMedia", {
    configurable: true,
    value: (query: string): MediaQueryList =>
      ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }) as unknown as MediaQueryList,
  });
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  cleanup();
});
