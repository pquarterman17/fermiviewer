import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useFourD } from "../../../store/fourd";
import FourDApertureControls from "./FourDApertureControls";

afterEach(() => {
  useFourD.getState().reset();
});

describe("FourDApertureControls — client-side aperture validation", () => {
  it("disables Compute map and explains why when the annulus radii are degenerate", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "custom", innerR: 40, outerR: 40, shape: "annulus",
      },
    });
    render(<FourDApertureControls detShape={[640, 640]} />);

    expect(screen.getByRole("button", { name: "Compute map" })).toBeDisabled();
    expect(screen.getByText(/inner radius/i)).toBeVisible();
  });

  it("disables Compute map when a manual center is not a finite number", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: NaN, centerKx: 9, autoCenter: false,
        mode: "custom", innerR: 5, outerR: 20, shape: "annulus",
      },
    });
    render(<FourDApertureControls detShape={[640, 640]} />);

    expect(screen.getByRole("button", { name: "Compute map" })).toBeDisabled();
    expect(
      screen.getByText("center (ky, kx) must be set when auto-center is off"),
    ).toBeVisible();
  });

  it("leaves Compute map enabled for a valid aperture", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "bf", innerR: 0, outerR: 80, shape: "circle",
      },
    });
    render(<FourDApertureControls detShape={[640, 640]} />);

    expect(screen.getByRole("button", { name: "Compute map" })).toBeEnabled();
  });
});
