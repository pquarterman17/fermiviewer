import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { useFourD } from "../../../store/fourd";
import { DEFAULT_HIGH_PASS_CUTOFF } from "../../../store/fourdComOutput";
import FourDComOutputFields from "./FourDComOutputFields";

afterEach(() => {
  useFourD.getState().reset();
});

function setAperture(overrides: { mradPerPx?: number | null; highPassCutoff?: number } = {}) {
  useFourD.setState((s) => ({
    aperture: {
      ...s.aperture,
      mradPerPx: null,
      highPassCutoff: DEFAULT_HIGH_PASS_CUTOFF,
      ...overrides,
    },
  }));
}

describe("FourDComOutputFields", () => {
  it("renders nothing for com mode — /com takes no calibration at all", () => {
    setAperture();
    const { container } = render(<FourDComOutputFields mode="com" cal={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows only the mrad/px field for dpc mode", () => {
    setAperture();
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    expect(screen.getByLabelText("detector mrad per pixel")).toBeVisible();
    expect(screen.queryByLabelText(/high-pass cutoff/)).toBeNull();
  });

  it("shows both mrad/px and high-pass cutoff fields for idpc mode", () => {
    setAperture();
    render(<FourDComOutputFields mode="idpc" cal={null} />);
    expect(screen.getByLabelText("detector mrad per pixel")).toBeVisible();
    expect(screen.getByLabelText(/high-pass cutoff/)).toBeVisible();
  });

  it("shows the mrad/px value already stored in the aperture", () => {
    setAperture({ mradPerPx: 2.5 });
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    expect(screen.getByLabelText("detector mrad per pixel")).toHaveValue(2.5);
  });

  it("is blank, not '0', while mrad/px has never been typed", () => {
    setAperture({ mradPerPx: null });
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    expect(screen.getByLabelText("detector mrad per pixel")).toHaveValue(null);
  });

  it("typing a mrad/px value updates the store", () => {
    setAperture();
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    fireEvent.change(screen.getByLabelText("detector mrad per pixel"), {
      target: { value: "3.2" },
    });
    expect(useFourD.getState().aperture.mradPerPx).toBe(3.2);
  });

  it("clearing the mrad/px field resets it to null, not 0 or NaN", () => {
    setAperture({ mradPerPx: 3.2 });
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    fireEvent.change(screen.getByLabelText("detector mrad per pixel"), {
      target: { value: "" },
    });
    expect(useFourD.getState().aperture.mradPerPx).toBeNull();
  });

  it("typing a high-pass cutoff value updates the store (idpc only)", () => {
    setAperture();
    render(<FourDComOutputFields mode="idpc" cal={null} />);
    fireEvent.change(screen.getByLabelText(/high-pass cutoff/), {
      target: { value: "0.1" },
    });
    expect(useFourD.getState().aperture.highPassCutoff).toBe(0.1);
  });

  it("shows the detector's own mrad/px as a hint when calibrated in mrad", () => {
    setAperture();
    render(<FourDComOutputFields mode="dpc" cal={{ scale: 0.1, units: "mrad" }} />);
    expect(screen.getByText("detector: 0.1 mrad/px")).toBeVisible();
  });

  it("shows no calibration hint when the detector's calibration isn't in mrad", () => {
    setAperture();
    render(<FourDComOutputFields mode="dpc" cal={{ scale: 0.5, units: "1/nm" }} />);
    expect(screen.queryByText(/detector:/)).toBeNull();
  });

  it("shows no calibration hint when the detector is uncalibrated", () => {
    setAperture();
    render(<FourDComOutputFields mode="dpc" cal={null} />);
    expect(screen.queryByText(/detector:/)).toBeNull();
  });
});
