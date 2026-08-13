import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import FourDProbeMarker from "./FourDProbeMarker";

describe("FourDProbeMarker", () => {
  it("positions and labels the probed pixel", () => {
    const { container } = render(
      <FourDProbeMarker position={{ x: 120, y: 80 }} pixel={[7, 19]} />,
    );
    const marker = container.querySelector<HTMLElement>(".fvd-fourdnav-mark");
    expect(marker).toHaveStyle({ left: "120px", top: "80px" });
    expect(marker).toHaveTextContent("r7 · c19");
    expect(marker).toHaveAttribute("aria-hidden", "true");
  });

  it("flips the label down near the top edge", () => {
    const { container } = render(
      <FourDProbeMarker position={{ x: 50, y: 2 }} pixel={[1, 1]} />,
    );
    const label = container.querySelector(".fvd-fourdnav-label");
    expect(label).toHaveClass("flip-down");
  });

  it("flips the label left near the right edge of the viewport", () => {
    const { container } = render(
      <FourDProbeMarker
        position={{ x: 190, y: 80 }}
        pixel={[1, 1]}
        viewport={{ w: 200, h: 200 }}
      />,
    );
    const label = container.querySelector(".fvd-fourdnav-label");
    expect(label).toHaveClass("flip-left");
  });
});
