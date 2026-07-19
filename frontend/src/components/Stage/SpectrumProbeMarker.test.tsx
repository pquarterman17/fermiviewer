import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import SpectrumProbeMarker from "./SpectrumProbeMarker";

describe("SpectrumProbeMarker", () => {
  it("positions and labels the sampled pixel", () => {
    const { container } = render(
      <SpectrumProbeMarker position={{ x: 120, y: 80 }} pixel={[7, 19]} />,
    );
    const marker = container.querySelector<HTMLElement>(".fvd-specnav-mark");
    expect(marker).toHaveStyle({ left: "120px", top: "80px" });
    expect(marker).toHaveTextContent("r7 · c19");
    expect(marker).toHaveAttribute("aria-hidden", "true");
  });
});
