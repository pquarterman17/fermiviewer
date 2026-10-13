// Vitest global setup: DOM shims, strict console handling, and cleanup.

import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeEach, vi } from "vitest";
import { cleanup } from "@testing-library/react";

type ConsoleLevel = "error" | "warn";
interface ExpectedConsoleMessage {
  level: ConsoleLevel;
  pattern: string | RegExp;
}

let expectedConsole: ExpectedConsoleMessage[] = [];
let observedConsole: { level: ConsoleLevel; args: unknown[] }[] = [];
let outsideTestConsole: { level: ConsoleLevel; args: unknown[] }[] = [];
let testRunning = false;
const realConsole = { error: console.error, warn: console.warn };

function captureConsole(level: ConsoleLevel, args: unknown[]): void {
  (testRunning ? observedConsole : outsideTestConsole).push({ level, args });
}

// Install the capture for the lifetime of this test file, rather than only
// between beforeEach/afterEach. This includes module evaluation, beforeAll,
// afterAll, and output from callbacks that escape the body of a test.
console.error = (...args: unknown[]) => captureConsole("error", args);
console.warn = (...args: unknown[]) => captureConsole("warn", args);

/** Declare console output that is part of the behavior under test. */
export function expectConsoleMessage(
  level: ConsoleLevel,
  pattern: string | RegExp,
): void {
  expectedConsole.push({ level, pattern });
}

export function expectConsoleError(pattern: string | RegExp): void {
  expectConsoleMessage("error", pattern);
}

export function expectConsoleWarning(pattern: string | RegExp): void {
  expectConsoleMessage("warn", pattern);
}

function formatConsoleArgs(args: unknown[]): string {
  return args.map((arg) => {
    if (arg instanceof Error) return arg.stack ?? arg.message;
    if (typeof arg === "string") return arg;
    try {
      return JSON.stringify(arg);
    } catch {
      return String(arg);
    }
  }).join(" ");
}

function matches(message: string, pattern: string | RegExp): boolean {
  if (typeof pattern === "string") return message.includes(pattern);
  pattern.lastIndex = 0;
  return pattern.test(message);
}

function consoleFailures(
  observed: { level: ConsoleLevel; args: unknown[] }[],
  expected: ExpectedConsoleMessage[],
): string[] {
  const missing = [...expected];
  const unexpected: string[] = [];
  for (const entry of observed) {
    const message = formatConsoleArgs(entry.args);
    const index = missing.findIndex((candidate) =>
      candidate.level === entry.level && matches(message, candidate.pattern));
    if (index >= 0) missing.splice(index, 1);
    else unexpected.push(`${entry.level}: ${message}`);
  }
  return [
    ...unexpected.map((message) => `Unexpected console.${message}`),
    ...missing.map(({ level, pattern }) =>
      `Expected console.${level} matching ${String(pattern)} was not observed`),
  ];
}

async function flushLateConsole(): Promise<void> {
  if (vi.isFakeTimers()) {
    await new Promise<void>((resolve) => queueMicrotask(resolve));
    return;
  }
  await new Promise<void>((resolve) => setTimeout(resolve, 0));
}

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

// jsdom has no ResizeObserver; SpectrumPlot uses one to keep its uPlot sized
// to its host div. Reachable from any workshop's Explore tab now (item 13
// generalised it to EELS too), not just the one test file that used to stub
// it locally — a global, guarded stub mirrors the matchMedia polyfill above
// and yields to a test's own stub (e.g. SpectrumPlot.test.tsx's mock plot).
if (typeof globalThis.ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  Object.defineProperty(globalThis, "ResizeObserver", {
    configurable: true,
    value: ResizeObserverStub,
  });
}

// jsdom deliberately does not implement canvas rendering unless the optional
// native canvas package is installed. Its default getContext() emits one noisy
// console error per call before returning null. Most component tests only need
// the honest "no rendering context" result; rendering-specific tests replace
// this method with the small context surface they exercise.
Object.defineProperty(HTMLCanvasElement.prototype, "getContext", {
  configurable: true,
  writable: true,
  value: () => null,
});

beforeEach(() => {
  localStorage.clear();
  expectedConsole = [];
  observedConsole = outsideTestConsole.splice(0);
  testRunning = true;
});

afterEach(async ({ task }) => {
  cleanup();
  await flushLateConsole();
  const failures = consoleFailures(observedConsole, expectedConsole);
  testRunning = false;
  if (failures.length && task.result?.state !== "fail") {
    throw new Error(failures.join("\n"));
  }
});

afterAll(async () => {
  await flushLateConsole();
  console.error = realConsole.error;
  console.warn = realConsole.warn;
  const failures = consoleFailures(outsideTestConsole, []);
  outsideTestConsole = [];
  if (failures.length) throw new Error(failures.join("\n"));
});
