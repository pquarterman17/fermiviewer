import { useId } from "react";

interface RegionOption {
  value: string;
  label: string;
}

export default function AnalysisRegionSelect({
  choice,
  options,
  disabled,
  onChange,
}: {
  choice: string;
  options: RegionOption[];
  disabled: boolean;
  onChange: (choice: string) => void;
}) {
  const id = useId();
  return (
    <div className="fvd-ws-row">
      <label className="k" htmlFor={id}>Region</label>
      <select
        id={id}
        value={choice}
        disabled={disabled}
        style={{ flex: 1, minWidth: 0 }}
        title="Limit analysis to a selected or named ROI"
        onChange={(event) => onChange(event.target.value)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </div>
  );
}
