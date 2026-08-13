import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import type { ImageMeta } from "../../../lib/api";
import { useFourD } from "../../../store/fourd";
import { useViewer } from "../../../store/viewer";
import { useFourDNavProbeSync } from "./useFourDNavProbeSync";

function navImageMeta(id: string): ImageMeta {
  return {
    id,
    name: id,
    kind: "image",
    shape: [4, 5],
    dtype: "float64",
    pixel_size: null,
    pixel_unit: "",
    value_unit: "",
    n_channels: null,
    energy_first: null,
    energy_last: null,
    energy_units: "",
    stage_tilt_deg: null,
    meta: {},
  };
}

afterEach(() => {
  useFourD.getState().reset();
  useViewer.setState({ captureMode: "none", fourdNavPixel: null, activeId: null });
});

describe("useFourDNavProbeSync", () => {
  it("does nothing while captureMode is not fourdnav", () => {
    useFourD.setState({ navMeta: navImageMeta("nav1"), probe: null });
    useViewer.setState({ captureMode: "none", fourdNavPixel: [3, 4], activeId: "nav1" });

    renderHook(() => useFourDNavProbeSync());

    expect(useFourD.getState().probe).toBeNull();
  });

  it("converts the published pixel to a 0-based scan position when the nav image is the active Stage image", () => {
    useFourD.setState({ navMeta: navImageMeta("nav1"), probe: null });
    useViewer.setState({ captureMode: "fourdnav", fourdNavPixel: [8, 42], activeId: "nav1" });

    renderHook(() => useFourDNavProbeSync());

    expect(useFourD.getState().probe).toEqual({ y: 7, x: 41 });
  });

  it("does not touch the probe when a different image is active on the Stage", () => {
    useFourD.setState({ navMeta: navImageMeta("nav1"), probe: null });
    useViewer.setState({
      captureMode: "fourdnav",
      fourdNavPixel: [8, 42],
      activeId: "some-other-image",
    });

    renderHook(() => useFourDNavProbeSync());

    expect(useFourD.getState().probe).toBeNull();
  });

  it("does not touch the probe when no nav image has been registered yet", () => {
    useFourD.setState({ navMeta: null, probe: null });
    useViewer.setState({ captureMode: "fourdnav", fourdNavPixel: [8, 42], activeId: "nav1" });

    renderHook(() => useFourDNavProbeSync());

    expect(useFourD.getState().probe).toBeNull();
  });

  it("updates the probe again as the published pixel moves (drag)", () => {
    useFourD.setState({ navMeta: navImageMeta("nav1"), probe: null });
    useViewer.setState({ captureMode: "fourdnav", fourdNavPixel: [1, 1], activeId: "nav1" });

    renderHook(() => useFourDNavProbeSync());
    expect(useFourD.getState().probe).toEqual({ y: 0, x: 0 });

    act(() => useViewer.getState().setFourdNavPixel([3, 5]));
    expect(useFourD.getState().probe).toEqual({ y: 2, x: 4 });
  });

  it("clears fourdnav capture mode on unmount", () => {
    useViewer.setState({ captureMode: "fourdnav" });
    const { unmount } = renderHook(() => useFourDNavProbeSync());

    unmount();

    expect(useViewer.getState().captureMode).toBe("none");
  });

  it("leaves an unrelated capture mode alone on unmount", () => {
    useViewer.setState({ captureMode: "roi" });
    const { unmount } = renderHook(() => useFourDNavProbeSync());

    unmount();

    expect(useViewer.getState().captureMode).toBe("roi");
  });
});
