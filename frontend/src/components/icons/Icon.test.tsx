import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import Icon, { ICON_NAMES } from "./Icon";

describe("Icon", () => {
  it("renders every icon with consistent decorative SVG semantics", () => {
    const { container } = render(
      <>{ICON_NAMES.map((name) => <Icon key={name} name={name} />)}</>,
    );
    const icons = container.querySelectorAll("svg.fvd-icon");
    expect(icons).toHaveLength(ICON_NAMES.length);
    for (const icon of icons) {
      expect(icon).toHaveAttribute("viewBox", "0 0 24 24");
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(icon).toHaveAttribute("focusable", "false");
      expect(icon.childElementCount).toBeGreaterThan(0);
    }
  });
});
