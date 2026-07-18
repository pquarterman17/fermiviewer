import {
  useEffect,
  useRef,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";

const FOCUSABLE = [
  "button:not([disabled])",
  "a[href]",
  "input:not([disabled]):not([type='hidden'])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1']):not([disabled])",
].join(",");

/** A matching element is only a real tab stop if it is actually rendered.
 *  focus() on a display:none / visibility:hidden node is a silent no-op, which
 *  would strand initial focus or dead-end the Tab wrap. */
function isVisible(el: HTMLElement): boolean {
  if (!el.isConnected) return false;
  if (el.closest("[inert]")) return false;
  // Computed visibility already accounts for inheritance, so the element's own
  // value is enough. display does NOT inherit, so an ancestor set to none has
  // to be looked for explicitly. Deliberately avoids offsetParent: it is null
  // for position:fixed subtrees and always null in jsdom, which has no layout.
  if (getComputedStyle(el).visibility !== "visible") return false;
  for (
    let node: HTMLElement | null = el;
    node;
    node = node.parentElement
  ) {
    if (getComputedStyle(node).display === "none") return false;
  }
  return true;
}

function focusableIn(dialog: HTMLElement): HTMLElement[] {
  return Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
    isVisible,
  );
}

interface ModalDialogProps {
  ariaLabel: string;
  children: ReactNode;
  className: string;
  onClose: () => void;
  onKeyDown?: (event: KeyboardEvent<HTMLDivElement>) => void;
  style?: React.CSSProperties;
}

/** Shared modal behavior: semantics, initial focus, focus trap, and restore. */
export default function ModalDialog({
  ariaLabel,
  children,
  className,
  onClose,
  onKeyDown,
  style,
}: ModalDialogProps) {
  const dialogRef = useRef<HTMLDivElement>(null);
  const previousFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    previousFocus.current =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const frame = requestAnimationFrame(() => {
      const dialog = dialogRef.current;
      if (!dialog || dialog.contains(document.activeElement)) return;
      const firstControl = focusableIn(dialog)[0];
      if (firstControl) firstControl.focus();
      else dialog.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      // Only restore to a node that is still in the document and rendered;
      // focus() on a detached element silently drops focus to <body>.
      const previous = previousFocus.current;
      if (previous && previous.isConnected && isVisible(previous)) {
        previous.focus();
      }
    };
  }, []);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    onKeyDown?.(event);
    if (event.defaultPrevented) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key !== "Tab") return;

    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = focusableIn(dialog);
    if (focusable.length === 0) {
      event.preventDefault();
      dialog.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    } else if (!dialog.contains(document.activeElement)) {
      event.preventDefault();
      (event.shiftKey ? last : first).focus();
    }
  };

  const handleBackdrop = (event: MouseEvent<HTMLDivElement>) => {
    if (event.target === event.currentTarget) onClose();
  };

  return (
    <div className="fvd-overlay-backdrop" onMouseDown={handleBackdrop}>
      <div
        ref={dialogRef}
        className={`fvd-glass ${className}`}
        style={style}
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        tabIndex={-1}
        onKeyDown={handleKeyDown}
      >
        {children}
      </div>
    </div>
  );
}
