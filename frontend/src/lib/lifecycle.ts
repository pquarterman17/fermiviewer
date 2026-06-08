// Client-presence socket: the server shuts itself down when the last
// tab disconnects (desktop-style lifecycle). Reconnects with backoff so
// a backend restart in dev doesn't strand the page. Connection state is
// published for the status bar's connected/offline segment.

import { create } from "zustand";

export const useConnection = create<{ connected: boolean }>(() => ({
  connected: false,
}));

export function connectLifecycle(): void {
  let delay = 500;

  const connect = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = () => {
      delay = 500;
      useConnection.setState({ connected: true });
    };
    ws.onclose = () => {
      useConnection.setState({ connected: false });
      window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 8000);
    };
    ws.onerror = () => ws.close();
  };

  connect();
}
