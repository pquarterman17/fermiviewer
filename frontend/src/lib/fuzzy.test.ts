// fuzzy.ts — command-palette subsequence matcher (⌘K ordering).

import { describe, expect, it } from "vitest";

import { fuzzy } from "./fuzzy";

describe("fuzzy", () => {
  it("empty needle matches everything with score 0", () => {
    expect(fuzzy("", "anything")).toEqual({ score: 0, hits: [] });
  });

  it("non-subsequence returns null", () => {
    expect(fuzzy("xyz", "open file")).toBeNull();
    expect(fuzzy("fo", "of")).toBeNull(); // order matters
  });

  it("is case-insensitive and reports hit indices", () => {
    const r = fuzzy("OF", "open file");
    expect(r).not.toBeNull();
    expect(r!.hits).toEqual([0, 5]);
  });

  it("consecutive runs beat scattered matches", () => {
    const run = fuzzy("fft", "fft mask")!;
    const scattered = fuzzy("fft", "fitft mask…t")!;
    expect(run.score).toBeGreaterThan(scattered.score);
  });

  it("word-start matches beat mid-word matches", () => {
    const wordStart = fuzzy("e", "export")!;
    const midWord = fuzzy("e", "open")!;
    expect(wordStart.score).toBeGreaterThan(midWord.score);
  });

  it("shorter haystack wins on ties", () => {
    const short = fuzzy("gif", "gif")!;
    const long = fuzzy("gif", "gif builder window")!;
    expect(short.score).toBeGreaterThan(long.score);
  });
});
