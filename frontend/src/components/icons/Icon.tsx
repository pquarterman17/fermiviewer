import type { ReactNode } from "react";

export type IconName =
  | "angle"
  | "box-profile"
  | "box-zoom"
  | "check"
  | "chevron-down"
  | "chevron-left"
  | "chevron-right"
  | "close"
  | "compare"
  | "crop"
  | "delete"
  | "distance"
  | "edit"
  | "fixed-zoom"
  | "flip-horizontal"
  | "flip-vertical"
  | "grid"
  | "hand"
  | "keyboard"
  | "list"
  | "moon"
  | "panel-left"
  | "panel-right"
  | "polyline"
  | "profile"
  | "plus"
  | "reset"
  | "roi"
  | "rotate-ccw"
  | "rotate-cw"
  | "ruler"
  | "save-crop"
  | "search"
  | "settings"
  | "sun"
  | "workspace"
  | "zoom-in"
  | "zoom-out";

export const ICON_NAMES: IconName[] = [
  "angle", "box-profile", "box-zoom", "check", "chevron-down", "chevron-left",
  "chevron-right", "close", "compare", "crop", "delete", "distance",
  "edit", "fixed-zoom", "flip-horizontal", "flip-vertical", "grid", "hand",
  "keyboard", "list", "moon", "panel-left", "panel-right", "polyline",
  "profile", "plus", "reset", "roi", "rotate-ccw", "rotate-cw", "ruler",
  "save-crop", "search", "settings", "sun", "workspace", "zoom-in", "zoom-out",
];

export default function Icon({
  name,
  size = 16,
  className = "",
}: {
  name: IconName;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      className={`fvd-icon${className ? ` ${className}` : ""}`}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {glyph(name)}
    </svg>
  );
}

function glyph(name: IconName): ReactNode {
  switch (name) {
    case "rotate-ccw":
      return <><path d="M4 4v6h6" /><path d="M5.8 17.5A8 8 0 1 0 4 10" /></>;
    case "rotate-cw":
      return <><path d="M20 4v6h-6" /><path d="M18.2 17.5A8 8 0 1 1 20 10" /></>;
    case "flip-horizontal":
      return <><path d="M12 3v18" strokeDasharray="2 2" /><path d="m8 8-4 4 4 4M16 8l4 4-4 4" /></>;
    case "flip-vertical":
      return <><path d="M3 12h18" strokeDasharray="2 2" /><path d="m8 8 4-4 4 4M8 16l4 4 4-4" /></>;
    case "hand":
      return <path d="M7.5 11V6.5a1.5 1.5 0 0 1 3 0V10 5a1.5 1.5 0 0 1 3 0v5-3.5a1.5 1.5 0 0 1 3 0V11 9a1.5 1.5 0 0 1 3 0v4.5c0 4.2-2.5 7-6.8 7h-1.4c-2.2 0-3.6-1.2-4.7-2.8L3.8 13.5a1.6 1.6 0 0 1 2.5-2Z" />;
    case "box-zoom":
      return <><rect x="4" y="4" width="13" height="13" rx="1" /><circle cx="16.5" cy="16.5" r="3.5" /><path d="m19 19 2 2M14.5 16.5h4M16.5 14.5v4" /></>;
    case "fixed-zoom":
      return <><path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5" /><path d="M8 12h8M12 8v8" /></>;
    case "distance":
      return <><path d="M4 6v12M20 6v12M5 12h14" /><path d="m8 9-3 3 3 3M16 9l3 3-3 3" /></>;
    case "profile":
      return <path d="M3 17h3l2-8 3 6 3-10 3 12h4" />;
    case "box-profile":
      return <><rect x="3.5" y="4.5" width="17" height="15" rx="1" /><path d="m6 15 3-6 3 7 3-5 3 4" /></>;
    case "polyline":
      return <><path d="m4 18 5-9 5 6 6-10" /><circle cx="4" cy="18" r="1.2" /><circle cx="9" cy="9" r="1.2" /><circle cx="14" cy="15" r="1.2" /><circle cx="20" cy="5" r="1.2" /></>;
    case "angle":
      return <><path d="m5 19 6-14 8 14" /><path d="M8.5 13.5a5 5 0 0 0 7 0" /></>;
    case "roi":
      return <rect x="4" y="6" width="16" height="12" rx="1.5" strokeDasharray="3 2" />;
    case "ruler":
      return <><path d="m5 18-2-2L16 3l5 5L8 21l-3-3Z" /><path d="m14 5 2 2M11 8l2 2M8 11l2 2M5 14l2 2" /></>;
    case "crop":
      return <><path d="M7 3v14a2 2 0 0 0 2 2h12M3 7h14a2 2 0 0 1 2 2v12" /><path d="m16 3-3 3M3 16l3-3" /></>;
    case "save-crop":
      return <><path d="M5 4h14v16H5z" strokeDasharray="3 2" /><path d="M12 7v8m-3-3 3 3 3-3" /></>;
    case "compare":
      return <><rect x="3" y="5" width="8" height="14" rx="1" /><rect x="13" y="5" width="8" height="14" rx="1" /></>;
    case "delete":
      return <><path d="m3 12 6-7h11v14H9l-6-7Z" /><path d="m12 9 5 6m0-6-5 6" /></>;
    case "reset":
      return <><path d="M4 4v6h6" /><path d="M5.5 17a8 8 0 1 0-1.5-7" /><path d="M12 8v4l3 2" /></>;
    case "zoom-in":
    case "zoom-out":
      return <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5M7.5 10.5h6" />{name === "zoom-in" && <path d="M10.5 7.5v6" />}</>;
    case "list":
      return <><path d="M8 6h12M8 12h12M8 18h12" /><circle cx="4" cy="6" r=".7" fill="currentColor" /><circle cx="4" cy="12" r=".7" fill="currentColor" /><circle cx="4" cy="18" r=".7" fill="currentColor" /></>;
    case "grid":
    case "workspace":
      return <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>;
    case "keyboard":
      return <><rect x="3" y="6" width="18" height="12" rx="2" /><path d="M6 10h.01M9 10h.01M12 10h.01M15 10h.01M18 10h.01M6 13h.01M9 13h.01M12 13h.01M15 13h.01M18 13h.01M8 16h8" /></>;
    case "moon":
      return <path d="M20 15.5A8 8 0 0 1 8.5 4 8.5 8.5 0 1 0 20 15.5Z" />;
    case "sun":
      return <><circle cx="12" cy="12" r="4" /><path d="M12 2v2M12 20v2M2 12h2M20 12h2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M19.1 4.9l-1.4 1.4M6.3 17.7l-1.4 1.4" /></>;
    case "panel-left":
      return <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></>;
    case "panel-right":
      return <><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M15 4v16" /></>;
    case "search":
      return <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m15.5 15.5 5 5" /></>;
    case "settings":
      return <><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6v.2h-4V21a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1a1.7 1.7 0 0 0 .3-1.9A1.7 1.7 0 0 0 3 14H2.8v-4H3a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3v-.2h4V3a1.7 1.7 0 0 0 1 1.6 1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1a1.7 1.7 0 0 0-.3 1.9 1.7 1.7 0 0 0 1.6 1h.2v4H21a1.7 1.7 0 0 0-1.6 1Z" /></>;
    case "plus":
      return <path d="M12 5v14M5 12h14" />;
    case "chevron-left":
      return <path d="m15 18-6-6 6-6" />;
    case "check":
      return <path d="m5 12 4 4L19 6" />;
    case "chevron-right":
      return <path d="m9 18 6-6-6-6" />;
    case "chevron-down":
      return <path d="m6 9 6 6 6-6" />;
    case "edit":
      return <><path d="M4 20h4L19 9l-4-4L4 16v4Z" /><path d="m13.5 6.5 4 4" /></>;
    case "close":
      return <path d="M6 6l12 12M18 6 6 18" />;
  }
}
