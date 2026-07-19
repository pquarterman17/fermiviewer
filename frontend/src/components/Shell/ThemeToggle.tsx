import { useAppearancePreviewState } from "../../store/appearancePreview";
import { useViewer } from "../../store/viewer";
import Icon from "../icons/Icon";

export default function ThemeToggle() {
  const savedTheme = useViewer((s) => s.theme);
  const toggleTheme = useViewer((s) => s.toggleTheme);
  const previewTheme = useAppearancePreviewState((s) => s.value?.theme ?? null);
  const theme = previewTheme ?? savedTheme;

  return (
    <button
      className="fvd-icon-btn"
      aria-label="Dark theme"
      aria-pressed={theme === "dark"}
      data-tip="Toggle theme"
      data-tip-key="⌘⇧L"
      onClick={toggleTheme}
    >
      <Icon name={theme === "dark" ? "moon" : "sun"} />
    </button>
  );
}
