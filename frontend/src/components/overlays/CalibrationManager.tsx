import { useViewer } from "../../store/viewer";
import CalibrationCenter from "./calibration/CalibrationCenter";
import ModalDialog from "./ModalDialog";

export default function CalibrationManager() {
  const open = useViewer((s) => s.calibOpen);
  const setOpen = useViewer((s) => s.setCalibOpen);
  if (!open) return null;

  return (
    <ModalDialog
      ariaLabel="Calibration Center"
      className="fvd-cal-center-modal"
      onClose={() => setOpen(false)}
    >
      <CalibrationCenter onClose={() => setOpen(false)} />
    </ModalDialog>
  );
}
