import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { AxisCalOut } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import FourDApertureControls from "./FourDApertureControls";

afterEach(() => {
  useFourD.getState().reset();
});

function axis(scale: number, units: string): AxisCalOut {
  return { scale, origin: 0, units };
}

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

describe("FourDApertureControls — mrad readout (PLAN_4DSTEM #14)", () => {
  it("stays px-only when the dataset carries no detector calibration", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "custom", innerR: 20, outerR: 80, shape: "annulus",
      },
    });
    render(
      <FourDApertureControls
        detShape={[640, 640]}
        detAxes={[axis(1, ""), axis(1, "")]}
      />,
    );

    expect(screen.getByText("20.0 px")).toBeVisible();
    expect(screen.getByText("80.0 px")).toBeVisible();
    expect(screen.queryByLabelText(/radius in /)).toBeNull();
  });

  it("shows a paired editable mrad field for both radii when calibrated", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: false,
        mode: "custom", innerR: 20, outerR: 80, shape: "annulus",
      },
    });
    render(
      <FourDApertureControls
        detShape={[640, 640]}
        detAxes={[axis(0.1, "mrad"), axis(0.1, "mrad")]}
      />,
    );

    const fields = screen.getAllByLabelText("radius in mrad");
    expect(fields).toHaveLength(2);
    // inner = 20 px * 0.1 = 2 mrad; outer = 80 px * 0.1 = 8 mrad
    expect(fields[0]).toHaveValue(2);
    expect(fields[1]).toHaveValue(8);
    expect(screen.getAllByText("mrad")).toHaveLength(2);
  });

  it("typing a new mrad value converts back to px and updates the aperture", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "custom", innerR: 0, outerR: 80, shape: "circle",
      },
    });
    render(
      <FourDApertureControls
        detShape={[640, 640]}
        detAxes={[axis(0.1, "mrad"), axis(0.1, "mrad")]}
      />,
    );

    const field = screen.getByLabelText("radius in mrad");
    fireEvent.change(field, { target: { value: "12.5" } });

    // 12.5 mrad / 0.1 mrad-per-px = 125 px, exactly — a broken conversion
    // factor (e.g. * instead of /) would land somewhere else entirely
    expect(useFourD.getState().aperture.outerR).toBe(125);
  });

  it("hides the mrad field when only one detector axis is calibrated", () => {
    useFourD.setState({
      selectedId: "d1",
      aperture: {
        centerKy: null, centerKx: null, autoCenter: true,
        mode: "bf", innerR: 0, outerR: 80, shape: "circle",
      },
    });
    render(
      <FourDApertureControls
        detShape={[640, 640]}
        detAxes={[axis(0.1, "mrad"), axis(1, "")]}
      />,
    );

    expect(screen.queryByLabelText(/radius in /)).toBeNull();
  });
});
