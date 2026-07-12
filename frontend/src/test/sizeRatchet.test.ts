/**
 * Frontend size ratchet — the TypeScript counterpart of the backend's
 * 500-line god-module ceiling (tests/test_repo_integrity.py).
 *
 * Every non-test source file must stay under GENERAL_CEILING. The five
 * legacy modules that predate this test are PINNED at their historical
 * size: they may only shrink. When an extraction lands, the test fails
 * until the pin is lowered to the new count — that is the ratchet
 * locking in the gain. Pins never move up; a feature that would push a
 * file past its pin must extract enough existing code to offset it, in
 * the same change. A pinned file that drops below the general ceiling
 * graduates: remove its pin.
 *
 * Why this exists: the MATLAB predecessor grew a 14k-line monolith and
 * the decomposition took weeks. The backend ceiling prevented that on
 * the Python side; a 2026-07 repo audit found the frontend quietly
 * re-running the same movie (api.ts hit ~2,050 lines before the domain
 * split). This test extends the discipline to TypeScript.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// vitest's root is frontend/ (vite.config.ts), in local runs and CI alike
const SRC_ROOT = join(process.cwd(), "src");

const GENERAL_CEILING = 800;

/** Slack before a shrunken file forces its pin down. Small edits don't
 * churn the pin; real extractions (> PIN_SLACK lines) must lock in. */
const PIN_SLACK = 50;

/** Legacy god modules, pinned at their 2026-07-11 physical line
 * counts. DOWN-ONLY. Never raise a pin; never add a new entry —
 * split the file instead. */
const PINNED: Record<string, number> = {
  "store/viewer.ts": 1778,
  "components/Shell/MenuBar.tsx": 1698,
  "components/Stage/Stage.tsx": 1403,
  "components/workshops/StructureWorkshop.tsx": 1353,
  "components/workshops/DiffractionWorkshop.tsx": 1090,
  "components/workshops/EelsWorkshop.tsx": 813,
};

function sourceFiles(dir: string, rel = ""): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(join(SRC_ROOT, dir === "." ? "" : dir), {
    withFileTypes: true,
  })) {
    const relPath = rel ? `${rel}/${entry.name}` : entry.name;
    if (entry.isDirectory()) {
      if (relPath === "test") continue; // fixtures/setup, not product code
      out.push(...sourceFiles(relPath, relPath));
    } else if (
      /\.(ts|tsx)$/.test(entry.name) &&
      !/\.test\.(ts|tsx)$/.test(entry.name) &&
      !entry.name.endsWith(".d.ts")
    ) {
      out.push(relPath);
    }
  }
  return out;
}

function lineCount(relPath: string): number {
  const text = readFileSync(join(SRC_ROOT, relPath), "utf8");
  if (text === "") return 0;
  const lines = text.split(/\r?\n/);
  if (lines[lines.length - 1] === "") lines.pop(); // trailing newline
  return lines.length;
}

describe("frontend size ratchet", () => {
  const counts = new Map(sourceFiles(".").map((f) => [f, lineCount(f)]));

  it("every pinned file still exists", () => {
    for (const pinned of Object.keys(PINNED)) {
      expect(counts.has(pinned), `${pinned} pinned but missing`).toBe(true);
    }
  });

  it("no unpinned source file exceeds the general ceiling", () => {
    const over = [...counts]
      .filter(([f, n]) => !(f in PINNED) && n > GENERAL_CEILING)
      .map(([f, n]) => `${f} (${n} > ${GENERAL_CEILING})`);
    expect(
      over,
      `split these files (do NOT add pins): ${over.join(", ")}`,
    ).toEqual([]);
  });

  it("pinned files never grow past their pin", () => {
    const grown = Object.entries(PINNED)
      .filter(([f, pin]) => (counts.get(f) ?? 0) > pin)
      .map(([f, pin]) => `${f} (${counts.get(f)} > pin ${pin})`);
    expect(
      grown,
      `extract enough code to offset the addition — never raise a pin: ${grown.join(", ")}`,
    ).toEqual([]);
  });

  it("pins track shrinkage (the ratchet only moves down)", () => {
    const stale = Object.entries(PINNED)
      .filter(([f, pin]) => {
        const n = counts.get(f) ?? 0;
        return n > GENERAL_CEILING && pin - n > PIN_SLACK;
      })
      .map(([f, pin]) => `${f}: lower pin ${pin} → ${counts.get(f)}`);
    expect(
      stale,
      `lock in the extraction by lowering the pin: ${stale.join(", ")}`,
    ).toEqual([]);
  });

  it("pins that reached the general ceiling are removed", () => {
    const graduated = Object.entries(PINNED)
      .filter(([f]) => (counts.get(f) ?? 0) <= GENERAL_CEILING)
      .map(([f]) => f);
    expect(
      graduated,
      `these files fit the general ceiling now — delete their pins: ${graduated.join(", ")}`,
    ).toEqual([]);
  });
});
