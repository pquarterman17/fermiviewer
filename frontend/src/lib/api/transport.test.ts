import { describe, expect, it } from "vitest";

import { formatApiDetail } from "./transport";

describe("formatApiDetail", () => {
  it("formats FastAPI validation details without object coercion", () => {
    expect(
      formatApiDetail(
        [
          {
            loc: ["body", "bg_width"],
            msg: "Input should be a valid number",
          },
          {
            loc: ["body", "e0_kev"],
            msg: "Input should be a valid number",
          },
        ],
        "Unprocessable Entity",
      ),
    ).toBe(
      "bg_width: Input should be a valid number; " +
        "e0_kev: Input should be a valid number",
    );
  });

  it("preserves string details and falls back for unknown shapes", () => {
    expect(formatApiDetail("bad window", "Error")).toBe("bad window");
    expect(formatApiDetail({ unexpected: true }, "Error")).toBe("Error");
  });
});
