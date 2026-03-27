import { useCallback, useEffect, useState } from "react";
import {
  fetchGraph,
  fetchExperimentDetail,
  editInput,
  editOutput,
  restartRun,
  eraseRun,
  updateThumbLabel,
  type BackendGraphNode,
  type BackendGraphEdge,
  type GraphPayload,
} from "../api";
import { subscribe } from "../serverEvents";
import type { Tag } from "../tags";

export interface GraphNode {
  id: string;
  step_id: number;
  label: string;
  input: Record<string, unknown>;
  output: Record<string, unknown>;
  border_color?: string;
  stack_trace?: string;
  model?: string;
  attachments?: unknown[];
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
}

export type EditKey = `${string}:${"Input" | "Output"}`;

type RerunState = "idle" | "starting" | "running";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function parseNodeData(raw: unknown): Record<string, unknown> {
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return isRecord(parsed) ? parsed : {};
    } catch {
      return {};
    }
  }
  return isRecord(raw) ? raw : {};
}

function parseGraphPayload(payload: GraphPayload): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = payload.nodes.map((node: BackendGraphNode) => ({
    id: node.uuid,
    step_id: node.step_id,
    label: node.label,
    input: parseNodeData(node.input),
    output: parseNodeData(node.output),
    border_color: node.border_color,
    stack_trace: node.stack_trace,
    model: node.model,
    attachments: node.attachments,
  }));
  const edges: GraphEdge[] = payload.edges.map((edge: BackendGraphEdge) => ({
    id: edge.id,
    source: edge.source_uuid,
    target: edge.target_uuid,
  }));
  return { nodes, edges };
}

export function useRunSessionState(sessionId: string) {
  const [thumbLabel, setThumbLabel] = useState<boolean | null>(null);
  const [selectedTags, setSelectedTags] = useState<Tag[]>([]);
  const [graphNodes, setGraphNodes] = useState<GraphNode[]>([]);
  const [graphEdges, setGraphEdges] = useState<GraphEdge[]>([]);
  const [loading, setLoading] = useState(true);
  const [rerunState, setRerunState] = useState<RerunState>("idle");
  const [editLock, setEditLock] = useState<EditKey | null>(null);
  const [editedFields, setEditedFields] = useState<Set<EditKey>>(new Set());
  const rerunning = rerunState !== "idle";

  const refreshSessionDetail = useCallback(async () => {
    const detail = await fetchExperimentDetail(sessionId);
    setThumbLabel(detail.thumb_label);
    setSelectedTags(detail.tags);
    return detail;
  }, [sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;

    async function load() {
      try {
        const [, graphResp] = await Promise.all([
          refreshSessionDetail(),
          fetchGraph(sessionId),
        ]);
        if (cancelled) return;
        const parsed = parseGraphPayload(graphResp.payload);
        setGraphNodes(parsed.nodes);
        setGraphEdges(parsed.edges);
      } catch (err) {
        console.error("Failed to load run data:", err);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [refreshSessionDetail, sessionId]);

  useEffect(() => {
    if (!sessionId) return;
    return subscribe("graph_update", (msg) => {
      if (msg.session_id !== sessionId) return;
      const parsed = parseGraphPayload(msg.payload as GraphPayload);
      setGraphNodes(parsed.nodes);
      setGraphEdges(parsed.edges);
    });
  }, [sessionId]);

  const handleStartEdit = useCallback((nodeId: string, label: "Input" | "Output") => {
    setEditLock(`${nodeId}:${label}`);
  }, []);

  const handleSaveEdit = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    const key: EditKey = `${nodeId}:${label}`;
    const updateField = label === "Input" ? editInput : editOutput;
    updateField(sessionId, nodeId, newData).catch(console.error);
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
  }, [sessionId]);

  const handleCancelEdit = useCallback(() => {
    setEditLock(null);
  }, []);

  const trackRerun = useCallback((promise: Promise<void>) => {
    setRerunState("starting");
    promise
      .then(() => setRerunState("running"))
      .catch((err) => {
        console.error(err);
        setRerunState("idle");
      });
  }, []);

  const handleSaveAndRerun = useCallback((nodeId: string, label: "Input" | "Output", newData: string) => {
    const key: EditKey = `${nodeId}:${label}`;
    const updateField = label === "Input" ? editInput : editOutput;
    trackRerun(updateField(sessionId, nodeId, newData).then(() => restartRun(sessionId)));
    setEditedFields((prev) => new Set(prev).add(key));
    setEditLock(null);
  }, [sessionId, trackRerun]);

  const handleRerun = useCallback(() => {
    trackRerun(restartRun(sessionId));
  }, [sessionId, trackRerun]);

  const handleThumbLabelToggle = useCallback((nextValue: boolean) => {
    const resolvedValue = thumbLabel === nextValue ? null : nextValue;
    setThumbLabel(resolvedValue);
    updateThumbLabel(sessionId, resolvedValue).catch(console.error);
  }, [sessionId, thumbLabel]);

  const handleErase = useCallback(() => {
    setEditedFields(new Set());
    setEditLock(null);
    trackRerun(eraseRun(sessionId));
  }, [sessionId, trackRerun]);

  useEffect(() => {
    if (!sessionId || rerunState === "idle") return;
    let cancelled = false;

    async function pollRunStatus() {
      try {
        const detail = await refreshSessionDetail();
        if (cancelled) return;
        if (rerunState === "running" && detail.status === "finished") {
          setRerunState("idle");
        }
      } catch (err) {
        if (!cancelled) console.error("Failed to refresh run status:", err);
      }
    }

    void pollRunStatus();
    const timer = window.setInterval(() => {
      void pollRunStatus();
    }, 500);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [refreshSessionDetail, rerunState, sessionId]);

    return {
      editedFields,
      editLock,
      graphEdges,
      graphNodes,
      handleCancelEdit,
      handleErase,
      handleRerun,
      handleThumbLabelToggle,
      handleSaveAndRerun,
      handleSaveEdit,
      handleStartEdit,
      loading,
      refreshSessionDetail,
      rerunning,
      selectedTags,
      setSelectedTags,
      thumbLabel,
    };
}
