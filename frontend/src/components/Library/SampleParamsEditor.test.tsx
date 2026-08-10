// SampleParamsEditor — the W4 item 23 deliverable: per-sample parameter
// editing via the shared ParamFieldRow widget, written through
// setGroupParams. Same store-mock pattern as Inspector/RegionsCard.test.tsx.

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ImageGroup } from "../../lib/groups";

const setGroupParamsFn = vi.fn();

const SAMPLE: ImageGroup = {
  id: "g1",
  name: "Sample A",
  ids: ["img1"],
  params: { anneal_temp: { value: 400, unit: "degC" }, substrate: { value: "MgO" } },
};

const state = {
  imageGroups: [SAMPLE] as ImageGroup[],
  setGroupParams: setGroupParamsFn,
};

vi.mock("../../store/viewer", () => ({
  useViewer: Object.assign(
    (sel: (s: typeof state) => unknown) => sel(state),
    { getState: () => state },
  ),
}));

import SampleParamsEditor from "./SampleParamsEditor";

describe("SampleParamsEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.imageGroups = [SAMPLE];
  });

  it("renders nothing for an unknown group id", () => {
    const { container } = render(<SampleParamsEditor groupId="nope" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists existing parameters with their current value and unit", () => {
    render(<SampleParamsEditor groupId="g1" />);
    expect(screen.getByText("Sample A")).toBeInTheDocument();
    expect(screen.getByText("anneal_temp")).toBeInTheDocument();
    expect(screen.getByDisplayValue("400")).toBeInTheDocument();
    expect(screen.getByLabelText("anneal_temp unit")).toHaveValue("degC");
    expect(screen.getByText("substrate")).toBeInTheDocument();
  });

  it("does not offer a unit field for a categorical (text) parameter", () => {
    render(<SampleParamsEditor groupId="g1" />);
    expect(screen.queryByLabelText("substrate unit")).not.toBeInTheDocument();
  });

  it("edits a numeric value on blur, keeping the existing unit", () => {
    render(<SampleParamsEditor groupId="g1" />);
    const input = screen.getByDisplayValue("400");
    // A single blur (value set directly, as a paste/tab-out would) avoids the
    // classic controlled-input revert: with this mocked store, a prior
    // "change" event's onChange doesn't mutate `state`, so React would
    // re-render the input back to its original value before blur fires.
    fireEvent.blur(input, { target: { value: "450" } });
    expect(setGroupParamsFn).toHaveBeenCalledWith("g1", {
      anneal_temp: { value: 450, unit: "degC" },
      substrate: { value: "MgO" },
    });
  });

  it("edits a parameter's unit", () => {
    render(<SampleParamsEditor groupId="g1" />);
    fireEvent.change(screen.getByLabelText("anneal_temp unit"), {
      target: { value: "K" },
    });
    expect(setGroupParamsFn).toHaveBeenCalledWith("g1", {
      anneal_temp: { value: 400, unit: "K" },
      substrate: { value: "MgO" },
    });
  });

  it("removes a parameter", () => {
    render(<SampleParamsEditor groupId="g1" />);
    fireEvent.click(screen.getByLabelText("Remove substrate"));
    expect(setGroupParamsFn).toHaveBeenCalledWith("g1", {
      anneal_temp: { value: 400, unit: "degC" },
    });
  });

  it("adds a new numeric parameter with a unit", () => {
    render(<SampleParamsEditor groupId="g1" />);
    fireEvent.change(screen.getByLabelText("New parameter name"), {
      target: { value: "thickness" },
    });
    fireEvent.change(screen.getByLabelText("New parameter unit"), {
      target: { value: "nm" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(setGroupParamsFn).toHaveBeenCalledWith("g1", {
      anneal_temp: { value: 400, unit: "degC" },
      substrate: { value: "MgO" },
      thickness: { value: 0, unit: "nm" },
    });
  });

  it("adds a categorical parameter with no unit field offered", () => {
    render(<SampleParamsEditor groupId="g1" />);
    fireEvent.change(screen.getByLabelText("New parameter name"), {
      target: { value: "notes" },
    });
    fireEvent.change(screen.getByLabelText("New parameter type"), {
      target: { value: "text" },
    });
    expect(screen.queryByLabelText("New parameter unit")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(setGroupParamsFn).toHaveBeenCalledWith("g1", {
      anneal_temp: { value: 400, unit: "degC" },
      substrate: { value: "MgO" },
      notes: { value: "", unit: null },
    });
  });

  it("does not add a parameter with an empty or duplicate name", () => {
    render(<SampleParamsEditor groupId="g1" />);
    expect(screen.getByRole("button", { name: /Add/ })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("New parameter name"), {
      target: { value: "substrate" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/ }));
    expect(setGroupParamsFn).not.toHaveBeenCalled();
  });
});
