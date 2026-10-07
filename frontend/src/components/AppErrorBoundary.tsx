// Last-resort render guard. Without it any render-time throw unmounts the
// whole React tree and leaves a blank window; with it the user gets the
// error text and a way back without losing the backend session.

import { Component, type ErrorInfo, type ReactNode } from "react";

interface State {
  error: Error | null;
}

export default class AppErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("FermiViewer render error", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" style={{ padding: 24, fontFamily: "var(--font-mono, monospace)" }}>
        <h2>Something went wrong</h2>
        <p>The view hit an error. Your open images are still loaded on the server.</p>
        <pre style={{ whiteSpace: "pre-wrap", opacity: 0.8 }}>{error.message}</pre>
        <button className="fvd-btn primary" onClick={() => this.setState({ error: null })}>
          Try again
        </button>{" "}
        <button className="fvd-btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
