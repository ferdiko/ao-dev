/**
 * Singleton WebSocket connection to the sovara server.
 *
 * Dispatches incoming messages by their `type` field to registered handlers.
 * Auto-reconnects on disconnection while there are active subscribers.
 */

type ServerEvent = {
  type: string;
  [key: string]: unknown;
};

type EventHandler = (data: ServerEvent) => void;

const listeners = new Map<string, Set<EventHandler>>();
const replayableEventTypes = new Set(["run_list"]);
const latestReplayableEvents = new Map<string, ServerEvent>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function connect() {
  if (ws) return;

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data) as unknown;
      if (!msg || typeof msg !== "object" || typeof (msg as { type?: unknown }).type !== "string") {
        return;
      }
      const typedMsg = msg as ServerEvent;
      if (replayableEventTypes.has(typedMsg.type)) {
        latestReplayableEvents.set(typedMsg.type, typedMsg);
      }
      const handlers = listeners.get(typedMsg.type);
      if (handlers) {
        for (const handler of handlers) handler(typedMsg);
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

  const latestEvent = latestReplayableEvents.get(eventType);
  if (latestEvent) {
    handler(latestEvent);
  }

  return () => {
    const set = listeners.get(eventType);
    if (set) {
      set.delete(handler);
      if (set.size === 0) listeners.delete(eventType);
    }
    if (listeners.size === 0) {
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (ws) {
        ws.close();
        ws = null;
      }
      latestReplayableEvents.clear();
    }
  };
}
