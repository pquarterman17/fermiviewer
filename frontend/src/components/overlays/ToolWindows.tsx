import { lazy, Suspense } from "react";

import { useViewer, type ToolKind } from "../../store/viewer";
import ToolWindow from "./ToolWindow";

const DiffractionWorkshop = lazy(() => import("../workshops/DiffractionWorkshop"));
const FftMaskWorkshop = lazy(() => import("../workshops/FftMaskWorkshop"));
const PixelInspector = lazy(() => import("../workshops/PixelInspector"));
const ColorOverlayWorkshop = lazy(() => import("../workshops/ColorOverlayWorkshop"));
const LayersWorkshop = lazy(() => import("../workshops/LayersWorkshop"));
const StructureWorkshop = lazy(() => import("../workshops/StructureWorkshop"));
const SurfaceView = lazy(() => import("../workshops/SurfaceView"));
const EdsWorkshop = lazy(() => import("../workshops/EdsWorkshop"));
const EelsWorkshop = lazy(() => import("../workshops/EelsWorkshop"));

const titles: Record<ToolKind, string> = {
  eels: "EELS",
  eds: "EDS",
  diffraction: "Diffraction",
  fftmask: "FFT Mask",
  pixels: "Pixel Inspector",
  structure: "Structure",
  overlay: "Color Overlay",
  surface: "Surface Plot",
  layers: "Cross-section Layers",
};

export default function ToolWindows() {
  const tools = useViewer((s) => s.tools);
  return tools.map((tool) => (
    <ToolWindow
      key={tool.kind}
      kind={tool.kind}
      title={titles[tool.kind]}
      x={tool.x}
      y={tool.y}
      z={tool.z}
      width={
        tool.kind === "diffraction" || tool.kind === "fftmask"
          ? 332
          : tool.kind === "pixels"
            ? 300
            : 360
      }
    >
      <Suspense
        fallback={
          <div className="fvd-tool-loading" role="status">
            Loading {titles[tool.kind]}…
          </div>
        }
      >
        <Workshop kind={tool.kind} />
      </Suspense>
    </ToolWindow>
  ));
}

function Workshop({ kind }: { kind: ToolKind }) {
  switch (kind) {
    case "eels":
      return <EelsWorkshop />;
    case "eds":
      return <EdsWorkshop />;
    case "diffraction":
      return <DiffractionWorkshop />;
    case "fftmask":
      return <FftMaskWorkshop />;
    case "pixels":
      return <PixelInspector />;
    case "structure":
      return <StructureWorkshop />;
    case "overlay":
      return <ColorOverlayWorkshop />;
    case "surface":
      return <SurfaceView />;
    case "layers":
      return <LayersWorkshop />;
  }
}
