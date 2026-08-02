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
const RoughnessWorkshop = lazy(() => import("../workshops/RoughnessWorkshop"));
const ElementalWorkshop = lazy(
  () => import("../workshops/ElementalWorkshop"),
);
const CrossSectionGuide = lazy(() => import("../workshops/CrossSectionGuide"));
const NoiseWorkshop = lazy(() => import("../workshops/NoiseWorkshop"));
const InterfaceWidthWorkshop = lazy(() => import("../workshops/InterfaceWidthWorkshop"));
const DefectWorkshop = lazy(() => import("../workshops/DefectWorkshop"));
const FourDWorkshop = lazy(() => import("../workshops/FourDWorkshop"));

const titles: Record<ToolKind, string> = {
  // Both kinds open the one workspace; the title says so, and the
  // modality badge inside says which physics the cube gets.
  eels: "Elemental Analysis",
  eds: "Elemental Analysis",
  diffraction: "Diffraction",
  fftmask: "FFT Mask",
  pixels: "Pixel Inspector",
  structure: "Structure",
  overlay: "Color Overlay",
  surface: "Surface Plot",
  roughness: "Surface Roughness",
  layers: "Cross-section Layers",
  crosssection: "Cross-section Assistant",
  noise: "Noise Analysis",
  "interface-width": "Interface Width",
  defects: "Defect Analysis",
  fourd: "4D-STEM Viewer",
};

const defaultWidths: Partial<Record<ToolKind, number>> = {
  layers: 520,
  crosssection: 640,
  structure: 480,
  eds: 680,
  eels: 680,
  diffraction: 680,
  fftmask: 332,
  pixels: 300,
  roughness: 620,
  noise: 620,
  "interface-width": 620,
  defects: 620,
  fourd: 640,
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
      width={defaultWidths[tool.kind] ?? 360}
      height={["eds", "eels", "diffraction", "fourd"].includes(tool.kind) ? 620 : undefined}
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
    // Both legacy kinds resolve to the one Elemental Analysis workspace; the
    // modality comes from the cube, not from which menu item was used, so a
    // restored session that saved kind "eels" still lands somewhere sensible.
    case "eels":
    case "eds":
      return <ElementalWorkshop />;
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
    case "roughness":
      return <RoughnessWorkshop />;
    case "layers":
      return <LayersWorkshop />;
    case "crosssection":
      return <CrossSectionGuide />;
    case "noise":
      return <NoiseWorkshop />;
    case "interface-width":
      return <InterfaceWidthWorkshop />;
    case "defects":
      return <DefectWorkshop />;
    case "fourd":
      return <FourDWorkshop />;
  }
}
