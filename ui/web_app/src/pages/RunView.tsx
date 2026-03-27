import { useState, useCallback, useMemo, useEffect, useRef } from "react";
import { useParams, useSearchParams, useNavigate } from "react-router-dom";
import {
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Node,
  type Edge,
  type NodeTypes,
  type NodeProps,
  type EdgeProps,
  type EdgeTypes,
  Handle,
  Position,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { Breadcrumb } from "../components/Breadcrumb";
import { RunTraceFlow } from "../components/RunTraceFlow";
import { RunTabsHeader } from "../components/RunTabsHeader";
import {
  fetchProject,
  fetchExperimentDetail,
  fetchProjectTags,
  createProjectTag,
  deleteProjectTag,
  updateRunTags,
  prefetchTrace,
} from "../api";
import { layoutGraph, type Point } from "../graphLayout";
import { Sparkles, RotateCcw, Loader2, Undo2, ThumbsUp, ThumbsDown, ChevronRight, PanelRight, X } from "lucide-react";
import { TraceChat } from "../components/TraceChat";
import { useRunGraphFocus, type GraphFocusApiHandle } from "../hooks/useRunGraphFocus";
import { useResize } from "../hooks/useResize";
import { useRunSessionState } from "../hooks/useRunSessionState";
import { useRunViewLayout, type RunViewLayoutState } from "../hooks/useRunViewLayout";
import { TagDropdown } from "../components/TagDropdown";
import type { Tag } from "../tags";
import { sortTagsByName } from "../tags";

// ── Custom LLM Node ────────────────────────────────────

function LLMNode({ data, selected }: NodeProps) {
  const d = data as {
    label: string;
    model?: string;
    nodeId: string;
    stepId?: number;
    focused?: boolean;
    borderColor?: string;
  };
  return (
    <div
      className={`graph-llm-node${selected ? " selected" : ""}${d.focused ? " focused" : ""}`}
      style={d.focused ? { borderColor: "#43884e" } : undefined}
    >
      <Handle type="target" position={Position.Top} id="top" className="graph-handle" />
      <Handle type="target" position={Position.Left} id="left" className="graph-handle graph-handle-side" />
      <Handle type="target" position={Position.Right} id="right" className="graph-handle graph-handle-side" />
      <div className={`graph-node-title-row${typeof d.stepId === "number" ? " has-step" : ""}`}>
        <div className="graph-node-label">{d.label}</div>
        {typeof d.stepId === "number" && <div className="graph-node-step">{`Step ${d.stepId}`}</div>}
      </div>
      {d.model && <div className="graph-node-model">{d.model}</div>}
      <Handle type="source" position={Position.Bottom} id="bottom" className="graph-handle" />
      <Handle type="source" position={Position.Left} id="left" className="graph-handle graph-handle-side" />
      <Handle type="source" position={Position.Right} id="right" className="graph-handle graph-handle-side" />
    </div>
  );
}

/** Custom edge that renders a polyline path from layout engine waypoints. */
function RoutedEdgeComponent({ id, data }: EdgeProps) {
  const d_ = data as Record<string, unknown>;
  const points = d_?.points as Point[] | undefined;
  const highlighted = d_?.highlighted as boolean;
  const color = highlighted ? "#43884e" : "var(--color-text-muted)";
  const strokeWidth = highlighted ? 2.5 : 1.5;
  if (!points || points.length < 2) return null;
  const d = points.reduce((acc, p, i) =>
    i === 0 ? `M ${p.x},${p.y}` : `${acc} L ${p.x},${p.y}`, "");
  const markerId = `arrow-${id}`;
  return (
    <>
      <defs>
        <marker id={markerId} markerWidth="8" markerHeight="8" refX="6" refY="4"
          orient="auto" markerUnits="userSpaceOnUse">
          <polygon points="0,0 8,4 0,8" fill={color} />
        </marker>
      </defs>
      <path d={d} markerEnd={`url(#${markerId})`}
        style={{ stroke: color, strokeWidth, fill: "none" }} />
    </>
  );
}

const nodeTypes: NodeTypes = { llmNode: LLMNode };
const edgeTypes: EdgeTypes = { routed: RoutedEdgeComponent };

type ViewMode = "pretty" | "json";

/** Exposes useReactFlow() methods to the parent via ref. */
function GraphApi({ apiRef }: { apiRef: React.MutableRefObject<GraphFocusApiHandle | null> }) {
  const { setCenter } = useReactFlow();
  useEffect(() => {
    apiRef.current = { setCenter };
    return () => { apiRef.current = null; };
  }, [setCenter, apiRef]);
  return null;
}

// ── Main RunView (tab shell) ──────────────────────────

export function RunView() {
  const { projectId, sessionId: rawSessionIds } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const [layoutState, setLayoutState, persistLayout] = useRunViewLayout();

  const sessionIds = useMemo(() => rawSessionIds?.split(",").filter(Boolean) ?? [], [rawSessionIds]);
  const activeSessionId = searchParams.get("active") ?? sessionIds[0];

  // Fetch project name once for breadcrumb
  const [projectName, setProjectName] = useState("");
  useEffect(() => {
    if (!projectId) return;
    fetchProject(projectId).then((p) => setProjectName(p.name)).catch(console.error);
  }, [projectId]);

  // Fetch run names for all open tabs
  const [tabNames, setTabNames] = useState<Map<string, string>>(new Map());
  const sessionIdsKey = sessionIds.join(",");
  useEffect(() => {
    if (!sessionIds.length) return;
    let cancelled = false;
    Promise.all(sessionIds.map((id) =>
      fetchExperimentDetail(id).then((d) => [id, d.run_name] as const).catch(() => [id, ""] as const)
    )).then((pairs) => {
      if (!cancelled) setTabNames(new Map(pairs));
    });
    return () => { cancelled = true; };
  }, [sessionIds]);

  const switchTab = useCallback((id: string) => {
    setSearchParams({ active: id });
  }, [setSearchParams]);

  const closeTab = useCallback((id: string) => {
    const remaining = sessionIds.filter((s) => s !== id);
    if (remaining.length === 0) {
      navigate(`/project/${projectId}`);
      return;
    }
    const newActive = id === activeSessionId
      ? remaining[Math.min(sessionIds.indexOf(id), remaining.length - 1)]
      : activeSessionId;
    navigate(`/project/${projectId}/run/${remaining.join(",")}?active=${newActive}`);
  }, [sessionIds, activeSessionId, projectId, navigate]);

  const isMultiTab = sessionIds.length > 1;

  if (!activeSessionId) {
    return (
      <div className="run-view">
        <div className="empty-state">
          <div className="empty-state-title">No run selected</div>
        </div>
      </div>
    );
  }

  if (!isMultiTab) {
    return (
      <div className="run-view">
        <Breadcrumb items={[
          { label: "Projects", to: "/" },
          { label: projectName || "Project", to: `/project/${projectId}` },
          { label: tabNames.get(sessionIds[0]) || sessionIds[0] || "Run" },
        ]} />
        <RunViewContent
          key={activeSessionId}
          projectId={projectId}
          sessionId={activeSessionId}
          layoutState={layoutState}
          setLayoutState={setLayoutState}
          persistLayout={persistLayout}
        />
      </div>
    );
  }

  return (
    <div className="run-view">
      <div className="run-view-panel">
        <RunTabsHeader
          activeSessionId={activeSessionId}
          onCloseTab={closeTab}
          onSwitchTab={switchTab}
          projectId={projectId}
          projectName={projectName}
          sessionIds={sessionIds}
          sessionIdsKey={sessionIdsKey}
          tabNames={tabNames}
        />
        <RunViewContent
          key={activeSessionId}
          projectId={projectId}
          sessionId={activeSessionId}
          layoutState={layoutState}
          setLayoutState={setLayoutState}
          persistLayout={persistLayout}
        />
      </div>
    </div>
  );
}

// ── RunViewContent (single-run body) ──────────────────

function RunViewContent({
  projectId,
  sessionId,
  layoutState,
  setLayoutState,
  persistLayout,
}: {
  projectId?: string;
  sessionId: string;
  layoutState: RunViewLayoutState;
  setLayoutState: React.Dispatch<React.SetStateAction<RunViewLayoutState>>;
  persistLayout: () => void;
}) {
  // UI state
  const [viewMode, setViewMode] = useState<ViewMode>("pretty");
  const {
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
  } = useRunSessionState(sessionId);
  const [projectTags, setProjectTags] = useState<Tag[]>([]);
  const [tagPendingDelete, setTagPendingDelete] = useState<Tag | null>(null);
  const [deletingTag, setDeletingTag] = useState(false);
  const [deleteTagError, setDeleteTagError] = useState<string | null>(null);

  const GRAPH_MIN = 180; const GRAPH_MAX = 600;
  const CHAT_MIN = 200; const CHAT_MAX = 700;
  const { graphWidth, chatWidth, chatCollapsed } = layoutState;
  const graphPanelRef = useRef<HTMLDivElement>(null);
  const chatPanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    prefetchTrace(sessionId);
  }, [sessionId]);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    fetchProjectTags(projectId)
      .then((tags) => {
        if (!cancelled) setProjectTags(sortTagsByName(tags));
      })
      .catch((error) => {
        if (!cancelled) console.error("Failed to load project tags:", error);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const reloadTags = useCallback(async () => {
    if (!projectId) return;
    const [tags] = await Promise.all([
      fetchProjectTags(projectId).then(sortTagsByName),
      refreshSessionDetail(),
    ]);
    setProjectTags(tags);
  }, [projectId, refreshSessionDetail]);

  const handleToggleTag = useCallback((tag: Tag) => {
    const alreadySelected = selectedTags.some((item) => item.tag_id === tag.tag_id);
    const nextTags = sortTagsByName(
      alreadySelected
        ? selectedTags.filter((item) => item.tag_id !== tag.tag_id)
        : [...selectedTags, tag],
    );
    setSelectedTags(nextTags);
    updateRunTags(sessionId, nextTags.map((item) => item.tag_id))
      .catch(async (error) => {
        console.error("Failed to update run tags:", error);
        await reloadTags().catch(console.error);
      });
  }, [reloadTags, selectedTags, sessionId, setSelectedTags]);

  const handleCreateTag = useCallback((name: string, color: string) => {
    if (!projectId) return;
    createProjectTag(projectId, name, color)
      .then(async (tag) => {
        const nextProjectTags = sortTagsByName([...projectTags, tag]);
        const nextSelectedTags = sortTagsByName([...selectedTags, tag]);
        setProjectTags(nextProjectTags);
        setSelectedTags(nextSelectedTags);
        await updateRunTags(sessionId, nextSelectedTags.map((item) => item.tag_id));
      })
      .catch(async (error) => {
        console.error("Failed to create tag:", error);
        await reloadTags().catch(console.error);
      });
  }, [projectId, projectTags, reloadTags, selectedTags, sessionId, setSelectedTags]);

  const handleDeleteTag = useCallback((tag: Tag) => {
    setDeleteTagError(null);
    setTagPendingDelete(tag);
  }, []);

  const closeDeleteTagModal = useCallback(() => {
    if (deletingTag) return;
    setTagPendingDelete(null);
    setDeleteTagError(null);
  }, [deletingTag]);

  const confirmDeleteTag = useCallback(async () => {
    if (!projectId || !tagPendingDelete) return;
    setDeleteTagError(null);
    setDeletingTag(true);
    try {
      await deleteProjectTag(projectId, tagPendingDelete.tag_id);
      setProjectTags((previous) => previous.filter((item) => item.tag_id !== tagPendingDelete.tag_id));
      setSelectedTags((previous) => previous.filter((item) => item.tag_id !== tagPendingDelete.tag_id));
      setTagPendingDelete(null);
    } catch (error) {
      console.error("Failed to delete tag:", error);
      setDeleteTagError(error instanceof Error ? error.message : "Failed to delete tag.");
      await reloadTags().catch(console.error);
    } finally {
      setDeletingTag(false);
    }
  }, [projectId, reloadTags, setSelectedTags, tagPendingDelete]);

  // Resize via direct DOM mutation to avoid re-rendering the entire tree per frame.
  // React state is synced once on mouseUp.
  const graphWidthRef = useRef(graphWidth);
  graphWidthRef.current = graphWidth;
  const chatWidthRef = useRef(chatWidth);
  chatWidthRef.current = chatWidth;

  const onGraphResize = useCallback((delta: number) => {
    graphWidthRef.current = Math.min(GRAPH_MAX, Math.max(GRAPH_MIN, graphWidthRef.current + delta));
    if (graphPanelRef.current) graphPanelRef.current.style.width = `${graphWidthRef.current}px`;
  }, []);
  const onGraphResizeEnd = useCallback(() => {
    setLayoutState((prev) => ({ ...prev, graphWidth: graphWidthRef.current }));
    persistLayout();
  }, [setLayoutState, persistLayout]);

  const onChatResize = useCallback((delta: number) => {
    chatWidthRef.current = Math.min(CHAT_MAX, Math.max(CHAT_MIN, chatWidthRef.current - delta));
    if (chatPanelRef.current) chatPanelRef.current.style.width = `${chatWidthRef.current}px`;
  }, []);
  const onChatResizeEnd = useCallback(() => {
    setLayoutState((prev) => ({ ...prev, chatWidth: chatWidthRef.current }));
    persistLayout();
  }, [setLayoutState, persistLayout]);

  const graphHandleDown = useResize("horizontal", onGraphResize, onGraphResizeEnd);
  const chatHandleDown = useResize("horizontal", onChatResize, onChatResizeEnd);

  const orderedGraphNodes = useMemo(
    () => [...graphNodes].sort((a, b) => a.step_id - b.step_id),
    [graphNodes]
  );

  // Compute full graph layout (positions + routed edges)
  const graphLayout = useMemo(
    () => layoutGraph(orderedGraphNodes, graphEdges),
    [orderedGraphNodes, graphEdges],
  );
  const sortedNodeIds = graphLayout.sortedIds;
  const {
    canvasRef,
    focusNodeById,
    focusedNodeId,
    graphApiRef: graphApi,
    nodeRefs,
  } = useRunGraphFocus({
    graphLayout,
    sortedNodeIds,
  });

  // ReactFlow data from layout engine
  const nodeById = useMemo(() => new Map(orderedGraphNodes.map((n) => [n.id, n])), [orderedGraphNodes]);
  const nodeIdByStepId = useMemo(
    () =>
      new Map(
        orderedGraphNodes
          .filter((node) => typeof node.step_id === "number")
          .map((node) => [String(node.step_id), node.id])
      ),
    [orderedGraphNodes]
  );

  const rfNodes: Node[] = useMemo(() => {
    return sortedNodeIds.map((id) => {
      const pos = graphLayout.positions.get(id);
      const node = nodeById.get(id);
      if (!pos || !node) return null;
      return {
        id,
        type: "llmNode",
        position: { x: pos.x, y: pos.y },
        data: {
          label: node.label,
          model: node.model,
          nodeId: id,
          stepId: node.step_id,
          borderColor: node.border_color,
        },
      };
    }).filter(Boolean) as Node[];
  }, [sortedNodeIds, graphLayout, nodeById]);

  const rfEdges: Edge[] = useMemo(() => {
    return graphLayout.edges.map((e) => ({
      id: e.id,
      source: e.source,
      target: e.target,
      type: "routed",
      sourceHandle: e.sourceHandle,
      targetHandle: e.targetHandle,
      data: { points: e.points, highlighted: e.source === focusedNodeId || e.target === focusedNodeId },
    }));
  }, [graphLayout, focusedNodeId]);

  const onNodeClick = useCallback((_: React.MouseEvent, node: Node) => {
    focusNodeById(node.id);
  }, [focusNodeById]);

  const onCardClick = useCallback((nodeId: string) => {
    focusNodeById(nodeId);
  }, [focusNodeById]);

  const onStepLabelClick = useCallback((nodeRef: string) => {
    focusNodeById(nodeIdByStepId.get(nodeRef) ?? nodeRef);
  }, [focusNodeById, nodeIdByStepId]);

  const nodesWithSelection = useMemo(
    () => rfNodes.map((n) => ({
      ...n,
      selected: n.id === focusedNodeId,
      data: { ...n.data, focused: n.id === focusedNodeId },
    })),
    [rfNodes, focusedNodeId]
  );

  const hasGraph = orderedGraphNodes.length > 0;

  if (loading) {
    return (
      <div className="empty-state">
        <Loader2 size={24} className="fa-spinner" />
        <div className="empty-state-title" style={{ marginTop: 12 }}>Loading run…</div>
      </div>
    );
  }

  return (
    <>
      <div className="run-view-columns">
      <div className="run-view-left">

      {/* Top bar */}
      <div className="run-top-bar">
        <div className="run-detail-header-title">Full Trace</div>
        <div className="run-detail-header-actions">
          <div className="view-mode-toggle">
            <button
              className={`view-mode-btn${viewMode === "pretty" ? " active" : ""}`}
              onClick={() => setViewMode("pretty")}
            >
              Pretty
            </button>
            <button
              className={`view-mode-btn${viewMode === "json" ? " active" : ""}`}
              onClick={() => setViewMode("json")}
            >
              JSON
            </button>
          </div>
          <button
            className="run-rerun-btn"
            onClick={handleRerun}
            disabled={rerunning}
            title="Re-run with edits"
          >
            {rerunning ? (
              <><Loader2 size={13} className="fa-spinner" /> Re-running…</>
            ) : (
              <><RotateCcw size={13} /> Re-run</>
            )}
          </button>
          <button
            className="run-rerun-btn run-reset-btn"
            onClick={handleErase}
            title="Reset run to original state"
          >
            <Undo2 size={13} /> Reset All Edits
          </button>
        </div>
      </div>

      <div className="run-tag-bar">
        <div className="run-tag-bar-label">Tags</div>
        <TagDropdown
          selectedTags={selectedTags}
          allTags={projectTags}
          onToggle={handleToggleTag}
          onCreate={handleCreateTag}
          onDelete={handleDeleteTag}
        />
      </div>

      <div className="run-view-body">
        {/* Left: Graph */}
        <div ref={graphPanelRef} className="run-graph-panel" style={{ width: graphWidth, flex: "none" }}>
          <div className="run-graph-canvas" ref={canvasRef}>
            {hasGraph ? (
              <ReactFlowProvider>
                <ReactFlow
                  nodes={nodesWithSelection}
                  edges={rfEdges}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  onNodeClick={onNodeClick}
                  proOptions={{ hideAttribution: true }}
                  nodesDraggable={false}
                  panOnDrag={false}
                  zoomOnScroll={false}
                  zoomOnPinch={false}
                  zoomOnDoubleClick={false}
                  preventScrolling
                >
                  <GraphApi apiRef={graphApi} />
                </ReactFlow>
              </ReactFlowProvider>
            ) : (
              <div className="empty-state">
                <div className="empty-state-title">No graph data</div>
              </div>
            )}

            {/* Focus indicator — arrowhead from right edge pointing inward */}
            <div className="graph-focus-arrow" />

            {/* Controls (bottom-right) */}
            <div className="graph-controls-panel">
              <button
                className={`graph-controls-btn${thumbLabel === true ? " active-pass" : ""}`}
                title={thumbLabel === true ? "Clear label" : "Mark thumbs up"}
                onClick={() => handleThumbLabelToggle(true)}
              >
                <ThumbsUp size={12} color={thumbLabel === true ? "#fff" : "#4caf50"} />
              </button>
              <button
                className={`graph-controls-btn${thumbLabel === false ? " active-fail" : ""}`}
                title={thumbLabel === false ? "Clear label" : "Mark thumbs down"}
                onClick={() => handleThumbLabelToggle(false)}
              >
                <ThumbsDown size={12} color={thumbLabel === false ? "#fff" : "#e05252"} />
              </button>
            </div>
          </div>
        </div>

        <div className="resize-handle resize-handle-h" onMouseDown={graphHandleDown} />
        {/* Center: I/O Detail */}
        <div className="run-detail-panel">
          <div className="run-detail-body">
            {hasGraph ? (
              <RunTraceFlow
                nodes={orderedGraphNodes}
                viewMode={viewMode}
                focusedNodeId={focusedNodeId}
                nodeRefs={nodeRefs}
                onCardClick={onCardClick}
                editLock={editLock}
                editedFields={editedFields}
                onStartEdit={handleStartEdit}
                onSaveEdit={handleSaveEdit}
                onSaveAndRerun={handleSaveAndRerun}
                onCancelEdit={handleCancelEdit}
              />
            ) : (
              <div className="empty-state" style={{ flex: 1 }}>
                <div className="empty-state-title">No graph data</div>
              </div>
            )}
          </div>
        </div>

      </div>
      </div>{/* end run-view-left */}

      {!chatCollapsed && <div className="resize-handle resize-handle-h" onMouseDown={chatHandleDown} />}
      <div ref={chatPanelRef} className={`run-chat-panel${chatCollapsed ? " collapsed" : ""}`} style={chatCollapsed ? undefined : { width: chatWidth, flex: "none" }}>
        {chatCollapsed ? (
          <div
            className="run-chat-collapsed"
            onClick={() => setLayoutState((prev) => ({ ...prev, chatCollapsed: false }))}
            title="Open chat"
          >
            <PanelRight size={14} className="run-chat-collapsed-toggle" />
            <Sparkles size={13} className="run-chat-collapsed-icon" />
            <div className="run-chat-collapsed-arrow">
              <ChevronRight size={11} style={{ transform: "rotate(180deg)" }} />
            </div>
          </div>
        ) : (
          <TraceChat
            sessionId={sessionId}
            onCollapse={() => setLayoutState((prev) => ({ ...prev, chatCollapsed: true }))}
            onStepLabelClick={onStepLabelClick}
          />
        )}
      </div>
      </div>
      {tagPendingDelete && (
        <div className="modal-overlay" onClick={closeDeleteTagModal}>
          <div className="modal" onClick={(event) => event.stopPropagation()}>
            <div className="modal-header">
              <h2 className="modal-title">Delete Tag</h2>
              <button className="modal-close" onClick={closeDeleteTagModal}>
                <X size={18} />
              </button>
            </div>
            <p className="modal-danger-warning">
              This will permanently delete <strong>{tagPendingDelete.name}</strong> from this project and remove it from all runs.
              This action cannot be undone.
            </p>
            {deleteTagError && <div className="modal-error">{deleteTagError}</div>}
            <div className="modal-actions">
              <button className="btn btn-secondary" onClick={closeDeleteTagModal} disabled={deletingTag}>
                Cancel
              </button>
              <button className="btn btn-danger" onClick={() => void confirmDeleteTag()} disabled={deletingTag}>
                {deletingTag ? "Deleting..." : "Delete tag"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
