import { useViewer } from "./viewer";
import { type StructureMode, useWorkshop } from "./workshop";

export function openStructureWorkshop(mode: StructureMode): void {
  useWorkshop.getState().setStructureMode(mode);
  useViewer.getState().openTool("structure");
}

export function openCrossSectionGuide(): void {
  useViewer.getState().openTool("crosssection");
}
