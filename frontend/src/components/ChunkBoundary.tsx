// Suspense plus a contained failure state for code-split UI. A lazy chunk
// that fails to download (backend restarted mid-session, a stale page after
// an upgrade) rejects its import; without a local guard that throw reaches
// AppErrorBoundary and replaces the whole window. Here it stays inside the
// panel that asked for it, with a reload as the way out — the backend keeps
// open images across reloads.

import { Component, Suspense, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** What failed, for the notice ("Compare view", "Preferences"). */
  label: string;
  /** Shown while the chunk downloads; nothing by default. */
  fallback?: ReactNode;
  /** Extra class on the notice, e.g. to float it when there is no host panel. */
  className?: string;
  /** Offered as "Close" so a failed overlay can be dismissed without a reload. */
  onDismiss?: () => void;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export default class ChunkBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`FermiViewer: ${this.props.label} failed to load`, error, info.componentStack);
  }

  render() {
    const { label, fallback = null, className, onDismiss, children } = this.props;
    const { error } = this.state;
    if (!error) return <Suspense fallback={fallback}>{children}</Suspense>;
    return (
      <div className={`fvd-chunk-error${className ? ` ${className}` : ""}`} role="alert">
        <strong>{label} failed to load</strong>
        <span>{error.message}</span>
        <div className="fvd-btn-row">
          <button className="fvd-btn primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          {onDismiss && (
            <button className="fvd-btn" onClick={onDismiss}>
              Close
            </button>
          )}
        </div>
      </div>
    );
  }
}
