import { describe, expect, it } from "vitest";

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
});
