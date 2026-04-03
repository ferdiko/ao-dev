/**
 * Singleton WebSocket connection to the Sovara server.
 *
 * Dispatches known incoming messages by their `type` field to registered
 * handlers and replays selected event types for late subscribers.
 */

import type { GraphPayload, Run } from "./runsApi";

export interface ProjectListChangedEvent {
  type: "project_list_changed";
}

export interface UserChangedEvent {
  type: "user_changed";
}

export interface RunListEvent {
  type: "run_list";
  runs: Run[];
  has_more: boolean;
}

export interface GraphUpdateEvent {
  type: "graph_update";
  run_id: string | null;
  payload: GraphPayload;
  active_runtime_seconds?: number | null;
}

export type ServerEvent =
  | GraphUpdateEvent
  | ProjectListChangedEvent
  | RunListEvent
  | UserChangedEvent;

export type ServerEventType = ServerEvent["type"];
export type ServerEventOf<T extends ServerEventType> = Extract<ServerEvent, { type: T }>;

type EventHandler<T extends ServerEventType> = (data: ServerEventOf<T>) => void;
type UntypedEventHandler = (data: ServerEvent) => void;

const listeners = new Map<ServerEventType, Set<UntypedEventHandler>>();
const replayableEventTypes = new Set<ServerEventType>(["run_list"]);
const latestReplayableEvents = new Map<ServerEventType, ServerEvent>();
let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isGraphPayload(value: unknown): value is GraphPayload {
  return isRecord(value)
    && Array.isArray(value.nodes)
    && Array.isArray(value.edges);
}

function parseServerEvent(value: unknown): ServerEvent | null {
  if (!isRecord(value) || typeof value.type !== "string") {
    return null;
  }

  switch (value.type) {
    case "project_list_changed":
      return { type: "project_list_changed" };
    case "user_changed":
      return { type: "user_changed" };
    case "run_list":
      if (!Array.isArray(value.runs) || typeof value.has_more !== "boolean") {
        return null;
      }
      return {
        type: "run_list",
        runs: value.runs as Run[],
        has_more: value.has_more,
      };
    case "graph_update":
      if ((value.run_id !== null && typeof value.run_id !== "string") || !isGraphPayload(value.payload)) {
        return null;
      }
      if (
        Object.prototype.hasOwnProperty.call(value, "active_runtime_seconds")
        && value.active_runtime_seconds !== null
        && typeof value.active_runtime_seconds !== "number"
      ) {
        return null;
      }
      return {
        type: "graph_update",
        run_id: value.run_id,
        payload: value.payload,
        active_runtime_seconds: value.active_runtime_seconds as number | null | undefined,
      };
    default:
      return null;
  }
}

function connect() {
  if (ws) return;

  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${protocol}//${location.host}/ws`);

  ws.onmessage = (event) => {
    try {
      const message = parseServerEvent(JSON.parse(event.data) as unknown);
      if (!message) {
        return;
      }

      if (replayableEventTypes.has(message.type)) {
        latestReplayableEvents.set(message.type, message);
      }

      const handlers = listeners.get(message.type);
      if (handlers) {
        for (const handler of handlers) {
          handler(message);
        }
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

export function subscribe<T extends ServerEventType>(
  eventType: T,
  handler: EventHandler<T>,
): () => void {
  const untypedHandler = handler as UntypedEventHandler;

  if (!listeners.has(eventType)) {
    listeners.set(eventType, new Set());
  }
  listeners.get(eventType)!.add(untypedHandler);

  if (!ws) connect();

  const latestEvent = latestReplayableEvents.get(eventType);
  if (latestEvent) {
    handler(latestEvent as ServerEventOf<T>);
  }

  return () => {
    const handlers = listeners.get(eventType);
    if (handlers) {
      handlers.delete(untypedHandler);
      if (handlers.size === 0) listeners.delete(eventType);
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
