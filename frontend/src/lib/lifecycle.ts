// Client-presence socket: the server shuts itself down when the last
// tab disconnects (desktop-style lifecycle). Reconnects with backoff so
// a backend restart in dev doesn't strand the page.

export function connectLifecycle(): void {
  let delay = 500;

  const connect = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = () => {
      delay = 500;
    };
    ws.onclose = () => {
      window.setTimeout(connect, delay);
      delay = Math.min(delay * 2, 8000);
    };
    ws.onerror = () => ws.close();
  };

  connect();
}
