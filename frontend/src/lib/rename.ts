// Single-image rename (audit D4) — shared by the filmstrip context
// menu and the F2 shortcut. Same backend path as Batch Rename.

import { askParams } from "../store/params";
import { useViewer } from "../store/viewer";
import { renameImage } from "./api";

export async function renameSingleImage(id: string): Promise<void> {
  const s = useViewer.getState();
  const meta = s.images[id];
  if (!meta) return;
  const v = await askParams("Rename Image", [
    { key: "name", label: "Name", type: "text", default: meta.name },
  ]);
  const name = (v?.["name"] as string | undefined)?.trim();
  if (!name || name === meta.name) return;
  try {
    const m = await renameImage(id, name);
    useViewer.setState((st) => ({ images: { ...st.images, [m.id]: m } }));
    s.setStatus(`renamed to ${m.name}`);
  } catch (e) {
    s.setStatus(`rename failed: ${(e as Error).message}`);
  }
}
