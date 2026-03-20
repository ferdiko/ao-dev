/**
 * Singleton WebSocket connection to the ao server.
 *
 * Dispatches incoming messages by their `type` field to registered handlers.
 * Auto-reconnects on disconnection while there are active subscribers.
 */

type EventHandler = (data: any) => void;

const listeners = new Map<string, Set<EventHandler>>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
  if (ws) return;

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      const handlers = listeners.get(msg.type);
      if (handlers) {
        for (const handler of handlers) handler(msg);
      }
    } catch {
      // Ignore parse errors (e.g. keepalive comments)
    }
  };

  ws.onclose = () => {
    ws = null;
    if (listeners.size > 0) {
      reconnectTimer = setTimeout(connect, 2000);
    }
  };

  ws.onerror = () => {
    ws?.close();
  };
}

/**
 * Subscribe to a specific server event type. Returns an unsubscribe function.
 * The WebSocket connection is established on first subscribe.
 */
export function subscribe(eventType: string, handler: EventHandler): () => void {
  if (!listeners.has(eventType)) {
    listeners.set(eventType, new Set());
  }
  listeners.get(eventType)!.add(handler);

  if (!ws) connect();

  return () => {
    const set = listeners.get(eventType);
    if (set) {
      set.delete(handler);
      if (set.size === 0) listeners.delete(eventType);
    }
    if (listeners.size === 0 && ws) {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws.close();
      ws = null;
    }
  };
}
