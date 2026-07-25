import { describe, expect, it } from "vitest";

import { finiteProfilePairs } from "./diagnostics";

describe("finiteProfilePairs", () => {
  it("drops missing and non-finite pairs without manufacturing zeroes", () => {
    expect(
      finiteProfilePairs(
        [0, 1, 2, Number.NaN, 4, 5],
        [10, null, 12, 13, Number.POSITIVE_INFINITY, 15],
      ),
    ).toEqual({
      x: [0, 2, 5],
      y: [10, 12, 15],
    });
  });

  it("keeps x and y paired when their lengths differ", () => {
    expect(finiteProfilePairs([0, 1, 2], [5])).toEqual({
      x: [0],
      y: [5],
    });
  });
});
