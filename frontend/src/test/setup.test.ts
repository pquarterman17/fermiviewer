import { beforeAll, describe, expect, it } from "vitest";

import { expectConsoleError, expectConsoleWarning } from "./setup";

describe("shared test environment", () => {
  it("provides a quiet no-context canvas default", () => {
    const canvas = document.createElement("canvas");
    expect(canvas.getContext("2d")).toBeNull();
    expect(canvas.getContext("webgl")).toBeNull();
  });

  it("allows explicitly expected console output", () => {
    expectConsoleError("intentional render failure");
    expectConsoleWarning(/intentional fallback/);
    console.error("intentional render failure");
    console.warn("intentional fallback");
  });

  it("captures console output from callbacks that outlive the test body", () => {
    expectConsoleError("intentional late failure");
    setTimeout(() => console.error("intentional late failure"), 0);
  });
});

describe("whole-file console capture", () => {
  beforeAll(() => console.warn("intentional suite setup warning"));

  it("attributes suite-hook output to the first test", () => {
    expectConsoleWarning("intentional suite setup warning");
  });
});
