import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  replaceRegionSets as apiReplaceRegionSets,
  type ImageMeta,
  type ProjectRegions,
} from "../../lib/api";
import { useViewer } from "../../store/viewer";
import RegionWorkspaceCard from "./RegionWorkspaceCard";

vi.mock("../../lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../lib/api")>()),
  replaceRegionSets: vi.fn(),
}));

const initialState = useViewer.getState();
const meta: ImageMeta = {
  id: "image-1",
  name: "sample.tif",
  kind: "image",
  shape: [64, 64],
  dtype: "uint16",
  pixel_size: 1,
  pixel_unit: "nm",
  value_unit: "counts",
  n_channels: null,
  energy_first: null,
  energy_last: null,
  energy_units: "",
  stage_tilt_deg: null,
  content_rows: null,
  meta: {},
};

const loaded: ProjectRegions = {
  schema: 1,
  classes: [{ id: "grain", label: "Grain", color: "#8b5cf6", note: null }],
  sets: [{
    id: "set-1",
    name: "Primary grains",
    image_id: "image-1",
    meta: {},
    regions: [{
      id: "grain-1",
      name: "Grain 1",
      region_class: "grain",
      meta: {},
      parts: [{
        mode: "include",
        shape: {
          kind: "polygon",
          outline: [[1, 1], [1, 8], [8, 8]],
          holes: [[[2, 2], [2, 3], [3, 3]]],
        },
      }],
    }],
  }],
};

beforeEach(() => {
  useViewer.setState(initialState, true);
  useViewer.setState({
    activeId: "image-1",
    images: { "image-1": meta },
    regions: { schema: 1, classes: [], sets: [] },
    regionUi: {
      selectedSetId: null,
      selectedRegionId: null,
      hiddenSetIds: [],
      hiddenRegionKeys: [],
    },
  });
  vi.mocked(apiReplaceRegionSets).mockImplementation(async (regions) => regions);
  vi.clearAllMocks();
});

describe("RegionWorkspaceCard", () => {
  it("turns the empty state into an image-bound set", async () => {
    render(<RegionWorkspaceCard />);
    expect(screen.getByText("No analysis regions on this image")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Create region set" }));

    await waitFor(() => expect(useViewer.getState().regions.sets).toHaveLength(1));
    expect(useViewer.getState().regions.sets[0]).toMatchObject({
      image_id: "image-1",
      name: "sample.tif regions",
    });
    expect(useViewer.getState().regionUi.selectedSetId).toBe("region-set");
  });

  it("makes compound geometry and classification scannable", () => {
    useViewer.setState({ regions: loaded });
    render(<RegionWorkspaceCard />);
    expect(screen.getByDisplayValue("Primary grains")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Grain 1")).toBeInTheDocument();
    expect(screen.getByText("1 part · 1 hole")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Region class" })).toHaveValue("grain");
  });

  it("keeps visibility presentational and accessible", async () => {
    useViewer.setState({ regions: loaded });
    render(<RegionWorkspaceCard />);
    const hide = screen.getByRole("button", { name: "Hide region" });
    expect(hide).toHaveAttribute("aria-pressed", "true");
    await userEvent.click(hide);
    expect(screen.getByRole("button", { name: "Show region" })).toHaveAttribute("aria-pressed", "false");
    expect(apiReplaceRegionSets).not.toHaveBeenCalled();
  });

  it("duplicates a region through the atomic server path", async () => {
    useViewer.setState({ regions: loaded });
    render(<RegionWorkspaceCard />);
    await userEvent.click(screen.getByTitle("Duplicate region"));
    await waitFor(() => expect(useViewer.getState().regions.sets[0].regions).toHaveLength(2));
    expect(useViewer.getState().regions.sets[0].regions[1].name).toBe("Grain 1 copy");
    expect(apiReplaceRegionSets).toHaveBeenCalledTimes(1);
  });
});
