import React, { useCallback, useEffect, useState, useRef, useMemo } from "react";
import ReactFlow, {
  Node,
  Edge,
  useNodesState,
  useEdgesState,
  ReactFlowProvider,
  useReactFlow
} from 'reactflow';
import 'reactflow/dist/style.css';
import { CustomNode } from './CustomNode';
import { CustomEdge } from './CustomEdge';
import { GraphNode, GraphEdge } from '../../types';
import { LayoutEngine } from '../../utils/layoutEngine';
import { MessageSender } from '../../types/MessageSender';
import styles from './GraphView.module.css';
import { NODE_WIDTH } from '../../utils/layoutConstants';
import { Tooltip } from '../common/Tooltip';

interface GraphViewProps {
  nodes: GraphNode[];
  edges: GraphEdge[];
  onNodeUpdate: (nodeId: string, field: keyof GraphNode, value: string) => void;
  session_id?: string;
  messageSender: MessageSender;
  isDarkTheme?: boolean;
  metadataPanel?: React.ReactNode;
  headerContent?: React.ReactNode;
  currentResult?: string;
  onResultChange?: (result: string) => void;
}

const nodeTypes = {
  custom: CustomNode,
};

const edgeTypes = {
  custom: CustomEdge,
};

// Inner component that has access to ReactFlow instance
const FlowWithViewport: React.FC<{
  nodes: Node[];
  edges: Edge[];
  onNodesChange: any;
  onEdgesChange: any;
  viewport: { x: number; y: number; zoom: number };
}> = ({ nodes, edges, onNodesChange, onEdgesChange, viewport }) => {
  const { setViewport: setRFViewport } = useReactFlow();

  // Apply viewport changes using ReactFlow's API
  useEffect(() => {
    setRFViewport(viewport, { duration: 0 });
  }, [viewport, setRFViewport]);

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      fitView={false}
      proOptions={{ hideAttribution: true }}
      minZoom={0.4}
      maxZoom={1}
      defaultViewport={viewport}
      nodesDraggable={false}
      nodesConnectable={false}
      elementsSelectable={true}
      panOnDrag={false}
      zoomOnScroll={false}
      zoomOnPinch={false}
      zoomOnDoubleClick={false}
      panOnScroll={false}
      preventScrolling={false}
      style={{
        width: "100%",
        height: "auto",
        padding: "0",
        margin: "0",
      }}
    />
  );
};

export const GraphView: React.FC<GraphViewProps> = ({
  nodes: initialNodes,
  edges: initialEdges,
  onNodeUpdate,
  session_id,
  messageSender,
  isDarkTheme = false,
  metadataPanel,
  headerContent,
  currentResult = '',
  onResultChange,
}) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);
  const [containerWidth, setContainerWidth] = useState(400);
  const [containerHeight, setContainerHeight] = useState(1500);
  const [viewport, setViewport] = useState<{ x: number; y: number; zoom: number }>({ x: 0, y: 0, zoom: 1 });
  const [isMetadataPanelOpen, setIsMetadataPanelOpen] = useState(false);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);

  // Compute connected nodes and edges for highlighting
  const { highlightedNodes, highlightedEdges } = useMemo(() => {
    if (!hoveredNodeId) {
      return { highlightedNodes: new Set<string>(), highlightedEdges: new Set<string>() };
    }

    const connectedNodes = new Set<string>([hoveredNodeId]);
    const connectedEdges = new Set<string>();

    initialEdges.forEach(edge => {
      if (edge.source === hoveredNodeId || edge.target === hoveredNodeId) {
        connectedNodes.add(edge.target);
        connectedNodes.add(edge.source);
        // Use layout engine edge ID format: `${source}-${target}` (no 'e' prefix)
        connectedEdges.add(`${edge.source}-${edge.target}`);
      }
    });

    return { highlightedNodes: connectedNodes, highlightedEdges: connectedEdges };
  }, [hoveredNodeId, initialEdges]);

  // Create layout engine instance using useMemo to prevent recreation
  const layoutEngine = useMemo(() => new LayoutEngine(), []);

  // Constants for metadata panel calculations
  const METADATA_PANEL_WIDTH = 350;
  const BUTTON_COLUMN_WIDTH = 52;

  // Store the calculated layout (node and edge positions) - this should be constant
  const layoutCacheRef = useRef<{
    flowNodes: Node[];
    flowEdges: Edge[];
    minXAll: number;
    maxXAll: number;
    widthSpan: number;
  } | null>(null);

  // Track previous structure and width to detect when layout recalc is needed
  const prevLayoutRef = useRef<{ nodeIds: string; edgeIds: string; width: number } | null>(null);

  const handleNodeUpdate = useCallback(
    (nodeId: string, field: keyof GraphNode, value: string) => {
      onNodeUpdate(nodeId, field, value);
      messageSender.send({
        type: 'update_node',
        node_id: nodeId,
        field,
        value,
        session_id
      });
      messageSender.send({ type: 'reset', id: Math.floor(Math.random() * 100000) });
    },
    [onNodeUpdate, session_id, messageSender]
  );

  // Calculate the graph layout (node and edge positions) - should only change when nodes/edges change
  const calculateLayout = useCallback(() => {
    // Don't calculate layout until we have actual container dimensions
    if (containerWidth === 0) return;

    // Use the current container width for layout calculation (responds to resize)
    const layout = layoutEngine.layoutGraph(initialNodes, initialEdges, containerWidth);

    // Calculate if we have left bands that need negative positioning
    const hasLeftBands = layout.edges.some(edge => edge.band?.includes('Left'));

    // Find the minimum X position to adjust for left bands
    let minX = 0;
    if (hasLeftBands) {
      layout.edges.forEach(edge => {
        if (edge.points && edge.points.length > 0) {
          edge.points.forEach(point => {
            if (point.x < minX) minX = point.x;
          });
        }
      });
    }

    // Adjust positions if we have negative X coordinates
    const xOffset = minX < 0 ? Math.abs(minX) + 20 : 0;

    const maxY = Math.max(0, ...Array.from(layout.positions.values()).map((pos) => pos.y)) + 300;
    setContainerHeight(maxY);

    const flowNodes: Node[] = initialNodes.map((node) => {
      const position = layout.positions.get(node.id) || { x: 0, y: 0 };
      return {
        id: node.id,
        type: "custom",
        position: { x: position.x + xOffset, y: position.y },
        data: {
          ...node,
          onUpdate: handleNodeUpdate,
          session_id,
          messageSender,
          isDarkTheme,
          onHover: setHoveredNodeId,
          isHighlighted: highlightedNodes.has(node.id),
        },
      };
    });

    const flowEdges: Edge[] = layout.edges.map((edge) => {
      // Adjust edge points if needed
      const adjustedPoints = edge.points.map(point => ({
        x: point.x + xOffset,
        y: point.y
      }));

      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: "custom",
        data: { points: adjustedPoints },
        animated: false,
      };
    });

    // Calculate bounding box for viewport calculations
    const PADDING_X = 40;
    const nodeMinX = flowNodes.length ? Math.min(...flowNodes.map(n => n.position.x)) : 0;
    const nodeMaxX = flowNodes.length ? Math.max(...flowNodes.map(n => n.position.x + NODE_WIDTH)) : 0;
    const edgeXs = flowEdges.flatMap(e => (e.data as any)?.points?.map((p: any) => p.x) ?? []);
    const edgesMinX = edgeXs.length ? Math.min(...edgeXs) : nodeMinX;
    const edgesMaxX = edgeXs.length ? Math.max(...edgeXs) : nodeMaxX;
    const minXAll = Math.min(nodeMinX, edgesMinX);
    const maxXAll = Math.max(nodeMaxX, edgesMaxX);
    const widthSpan = Math.max(1, maxXAll - minXAll);

    // Store the layout in cache
    layoutCacheRef.current = {
      flowNodes,
      flowEdges,
      minXAll,
      maxXAll,
      widthSpan,
    };

    setNodes(flowNodes);
    setEdges(flowEdges);

    // Immediately calculate and update viewport after layout changes
    const bboxW = widthSpan + PADDING_X * 2;
    const availableW = Math.max(1, containerWidth);
    const zoom = Math.min(1, availableW / bboxW);
    const x = -minXAll * zoom + (availableW - widthSpan * zoom) / 2;
    setViewport({ x, y: 0, zoom });
  }, [
    initialNodes,
    initialEdges,
    handleNodeUpdate,
    setNodes,
    setEdges,
    session_id,
    messageSender,
    isDarkTheme,
    layoutEngine,
    containerWidth
  ]);

  // Calculate viewport (zoom and position) based on current container width
  const updateViewport = useCallback(() => {
    if (!layoutCacheRef.current) return;

    const { minXAll, widthSpan } = layoutCacheRef.current;
    const PADDING_X = 40;
    const bboxW = widthSpan + PADDING_X * 2;
    const availableW = Math.max(1, containerWidth);
    const zoom = Math.min(1, availableW / bboxW);
    const x = -minXAll * zoom + (availableW - widthSpan * zoom) / 2;

    setViewport({ x, y: 0, zoom });
  }, [containerWidth]);

  // Recalculate layout when structure or width changes, or update data in place if only content changed
  useEffect(() => {
    // Don't process until we have container dimensions
    if (containerWidth === 0) return;

    const currentNodeIds = initialNodes.map(n => n.id).sort().join(',');
    const currentEdgeIds = initialEdges.map(e => e.id).sort().join(',');
    const prev = prevLayoutRef.current;

    const structureChanged = !prev || prev.nodeIds !== currentNodeIds || prev.edgeIds !== currentEdgeIds;
    const widthChanged = !prev || prev.width !== containerWidth;

    if (structureChanged || widthChanged) {
      // Structure or width changed - need full layout recalculation
      calculateLayout();
      prevLayoutRef.current = { nodeIds: currentNodeIds, edgeIds: currentEdgeIds, width: containerWidth };
    } else {
      // Only data changed - update node data in place without layout recalc
      setNodes(currentNodes => currentNodes.map(node => {
        const updatedData = initialNodes.find(n => n.id === node.id);
        if (updatedData) {
          return {
            ...node,
            data: {
              ...node.data,
              ...updatedData,
              onUpdate: handleNodeUpdate,
              session_id,
              messageSender,
              isDarkTheme,
            },
          };
        }
        return node;
      }));
    }
  }, [initialNodes, initialEdges, calculateLayout, setNodes, handleNodeUpdate, session_id, messageSender, isDarkTheme, containerWidth]);

  // Update viewport when container width changes (metadata panel opens/closes)
  useEffect(() => {
    updateViewport();
  }, [updateViewport]);

  // Update highlight state when hoveredNodeId changes (without recalculating layout)
  useEffect(() => {
    setNodes(currentNodes => currentNodes.map(node => ({
      ...node,
      data: {
        ...node.data,
        isHighlighted: highlightedNodes.has(node.id),
        onHover: setHoveredNodeId,
      },
    })));
    // Update edge styles - React Flow watches the style prop for changes
    // Sort edges so highlighted ones render last (on top)
    setEdges(currentEdges => currentEdges.map(edge => {
      const isHighlighted = highlightedEdges.has(edge.id);
      return {
        ...edge,
        // Use style prop to trigger React Flow re-render, pass isHighlighted via strokeWidth
        style: { strokeWidth: isHighlighted ? 2 : 1 },
        data: {
          ...edge.data,
          isHighlighted,
        },
      };
    }).sort((a, b) => {
      const aHighlighted = a.data?.isHighlighted ? 1 : 0;
      const bHighlighted = b.data?.isHighlighted ? 1 : 0;
      return aHighlighted - bHighlighted;
    }));
  }, [highlightedNodes, highlightedEdges, setNodes, setEdges]);

  // Handle container width changes for viewport adjustments
  useEffect(() => {
    const handleResize = () => {
      if (containerRef.current) {
        const totalWidth = containerRef.current.offsetWidth;

        // Calculate current available width for graph, accounting for metadata panel and button column
        let graphAvailableWidth = totalWidth - BUTTON_COLUMN_WIDTH;
        if (isMetadataPanelOpen && metadataPanel) {
          graphAvailableWidth -= METADATA_PANEL_WIDTH;
        }

        setContainerWidth(graphAvailableWidth);
      }
    };

    handleResize();

    const resizeObserver = new ResizeObserver(handleResize);
    if (containerRef.current) {
      resizeObserver.observe(containerRef.current);
    }

    return () => {
      resizeObserver.disconnect();
    };
  }, [isMetadataPanelOpen, metadataPanel, METADATA_PANEL_WIDTH, BUTTON_COLUMN_WIDTH]);

  // Always show the metadata button if we have a metadata panel
  const showMetadataButton = !!metadataPanel;

  const restartButtonStyle: React.CSSProperties = {
    width: '32px',
    height: '32px',
    borderRadius: '50%',
    background: 'transparent',
    border: 'none',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    boxShadow: '0 1px 4px rgba(0,0,0,0.08)',
    cursor: 'pointer',
    outline: 'none',
    padding: 0,
    position: 'relative',
  };

  return (
    <div
      ref={containerRef}
      className={styles.container}
      style={{
        width: "100%",
        height: "100%",
        minHeight: "100vh",
        fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
        display: "flex",
        flexDirection: "row",
        overflow: "hidden",
      }}
    >
      {/* Left Section: Graph content */}
      <div
        style={{
          flex: 1,
          position: "relative",
          minWidth: 0,
          overflow: "auto",
          display: "flex",
          flexDirection: "column",
          alignItems: "stretch",
        }}
      >
        {/* Header content that scrolls with the graph */}
        {headerContent}

        {/* Graph */}
        <div
          style={{
            display: "flex",
            alignItems: "flex-start",
            justifyContent: "center",
            paddingTop: headerContent ? "100px" : "120px",
          }}
        >
          <ReactFlowProvider>
            <div
              className={styles.flowContainer}
              style={{
                width: "100%",
                height: `${containerHeight}px`,
                marginTop: "0px",
                paddingTop: "0px",
              }}
            >
              <FlowWithViewport
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                viewport={viewport}
              />
            </div>
          </ReactFlowProvider>
        </div>
      </div>


      {/* Right Section: Fixed side panel (metadata + action buttons) */}
      <div
        style={{
          position: 'fixed',
          top: '0px',
          right: 0,
          bottom: 0,
          display: 'flex',
          flexDirection: 'row',
          zIndex: 200,
        }}
      >
        {/* Metadata Panel */}
        {isMetadataPanelOpen && showMetadataButton && metadataPanel && (
          <div
            style={{
              width: '350px',
              height: '100%',
              backgroundColor: isDarkTheme ? "#252525" : "#F0F0F0",
              borderLeft: `1px solid ${isDarkTheme ? '#3c3c3c' : '#e0e0e0'}`,
              display: 'flex',
              flexDirection: 'column',
              overflowY: 'auto',
            }}
          >
            {metadataPanel}
          </div>
        )}

        {/* Action Buttons Column */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "flex-start",
            gap: 4,
            padding: "10px",
            backgroundColor: isDarkTheme
              ? "var(--vscode-sideBar-background, #252526)"
              : "var(--vscode-sideBar-background, #f3f3f3)",
            borderLeft: isDarkTheme
              ? "1px solid var(--vscode-panel-border, #3c3c3c)"
              : "1px solid var(--vscode-panel-border, #e0e0e0)",
            minWidth: "35px",
            flexShrink: 0,
          }}
        >
          {/* Metadata Panel Toggle Button */}
          {showMetadataButton && (
            <Tooltip content={isMetadataPanelOpen ? "Hide run info" : "Show run info"} position="left" isDarkTheme={isDarkTheme}>
              <button
                style={{
                  ...restartButtonStyle,
                  background: isMetadataPanelOpen
                    ? (isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(220, 220, 220, 1)")
                    : (isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)"),
                  marginBottom: "4px",
                  border: `1px solid ${isDarkTheme ? "#555" : "#ddd"}`,
                }}
                onClick={() => {
                  setIsMetadataPanelOpen(!isMetadataPanelOpen);
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(255, 255, 255, 1)";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = isMetadataPanelOpen
                    ? (isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(220, 220, 220, 1)")
                    : (isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)");
                }}
              >
                {/* Codicon tag icon */}
                <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#d4a825">
                  <path d="M11 6C10.4477 6 10 5.55228 10 5C10 4.44772 10.4477 4 11 4C11.5523 4 12 4.44772 12 5C12 5.55228 11.5523 6 11 6ZM2.58722 10.1357C1.80426 9.3566 1.80426 8.0934 2.58722 7.31428L7.32688 2.59785C7.70082 2.22574 8.20735 2.01572 8.73617 2.01353L11.9867 2.00002C13.1029 1.99538 14.008 2.89877 13.9999 4.00947L13.9755 7.3725C13.9717 7.89662 13.7608 8.3982 13.3884 8.76882L8.71865 13.4157C7.93569 14.1948 6.66627 14.1948 5.88331 13.4157L2.58722 10.1357ZM3.29605 8.01964C2.90458 8.4092 2.90458 9.0408 3.29606 9.43036L6.59214 12.7103C6.98362 13.0999 7.61834 13.0999 8.00982 12.7103L12.6795 8.06346C12.8658 7.87815 12.9712 7.62736 12.9731 7.3653L12.9975 4.00227C13.0016 3.44692 12.549 2.99522 11.9909 2.99754L8.74036 3.01105C8.47595 3.01215 8.22268 3.11716 8.03571 3.30321L3.29605 8.01964Z"/>
                </svg>
              </button>
            </Tooltip>
          )}

          <Tooltip content="Erase all edits" position="left" isDarkTheme={isDarkTheme}>
            <button
              style={{
                ...restartButtonStyle,
                background: isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)",
                marginBottom: "4px",
                border: `1px solid ${isDarkTheme ? "#555" : "#ddd"}`,
              }}
              onClick={() => {
                if (!session_id) {
                  alert("No session_id available for erase! This is a bug.");
                  throw new Error("No session_id available for erase!");
                }
                messageSender.send({ type: "erase", session_id });
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(255, 255, 255, 1)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)";
              }}
            >
              {/* Codicon eraser icon */}
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#e05252">
                <path d="M14.5 6C14.5 5.6 14.344 5.223 14.061 4.939L11.062 1.939C10.496 1.372 9.504 1.372 8.94 1.939L1.439 9.439C1.156 9.722 1 10.099 1 10.5C1 10.901 1.156 11.277 1.439 11.561L3.439 13.561C3.722 13.844 4.099 14 4.5 14H11.5C11.776 14 12 13.776 12 13.5C12 13.224 11.776 13 11.5 13H8.121L14.06 7.061C14.343 6.778 14.499 6.401 14.499 6H14.5ZM4.146 12.854L2.146 10.854C2.051 10.759 2 10.634 2 10.5C2 10.366 2.052 10.241 2.146 10.146L4.293 8L8 11.707L6.707 13H4.5C4.366 13 4.241 12.948 4.146 12.854ZM13.354 6.354L8.708 11L5.001 7.293L9.648 2.646C9.742 2.552 9.867 2.5 10.001 2.5C10.135 2.5 10.26 2.552 10.355 2.646L13.355 5.646C13.45 5.741 13.501 5.866 13.501 6C13.501 6.134 13.448 6.259 13.354 6.354Z"/>
              </svg>
            </button>
          </Tooltip>
          <Tooltip content="Rerun" position="left" isDarkTheme={isDarkTheme}>
            <button
              style={{
                ...restartButtonStyle,
                marginBottom: "8px",
                background: isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)",
                border: `1px solid ${isDarkTheme ? "#555" : "#ddd"}`,
              }}
              onClick={() => {
                if (!session_id) {
                  alert("No session_id available for restart! This is a bug.");
                  throw new Error("No session_id available for restart!");
                }
                messageSender.send({ type: "restart", session_id });
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(255, 255, 255, 1)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)";
              }}
            >
              {/* Codicon debug-restart icon */}
              <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill="#7fc17b">
                <path d="M12.9991 8C12.9991 5.23858 10.7605 3 7.99909 3C6.36382 3 4.91128 3.78495 3.99863 5H5.99909C6.27524 5 6.49909 5.22386 6.49909 5.5C6.49909 5.77614 6.27524 6 5.99909 6H3.10868C3.10184 6.00014 3.09498 6.00014 3.08812 6H2.99909C2.72295 6 2.49909 5.77614 2.49909 5.5V2.5C2.49909 2.22386 2.72295 2 2.99909 2C3.27524 2 3.49909 2.22386 3.49909 2.5V4.03138C4.59815 2.78613 6.20656 2 7.99909 2C11.3128 2 13.9991 4.68629 13.9991 8C13.9991 11.3137 11.3128 14 7.99909 14C4.86898 14 2.29916 11.6035 2.02353 8.54488C1.99875 8.26985 2.20161 8.0268 2.47664 8.00202C2.75167 7.97723 2.99471 8.1801 3.0195 8.45512C3.2491 11.003 5.39117 13 7.99909 13C10.7605 13 12.9991 10.7614 12.9991 8Z"/>
              </svg>
            </button>
          </Tooltip>

          {/* Spacer to push result buttons to bottom */}
          <div style={{ flex: 1 }} />

          {/* Result Buttons */}
          {onResultChange && (
            <>
              <Tooltip content={currentResult === 'Satisfactory' ? "Clear result" : "Mark as Satisfactory"} position="left" isDarkTheme={isDarkTheme}>
                <button
                  style={{
                    ...restartButtonStyle,
                    marginBottom: "4px",
                    background: currentResult === 'Satisfactory'
                      ? '#4caf50'
                      : (isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)"),
                    border: `1px solid ${isDarkTheme ? "#555" : "#ddd"}`,
                  }}
                  onClick={() => onResultChange(currentResult === 'Satisfactory' ? '' : 'Satisfactory')}
                  onMouseEnter={(e) => {
                    if (currentResult !== 'Satisfactory') {
                      e.currentTarget.style.background = isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(255, 255, 255, 1)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (currentResult !== 'Satisfactory') {
                      e.currentTarget.style.background = isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)";
                    }
                  }}
                >
                  {/* Codicon pass icon */}
                  <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill={currentResult === 'Satisfactory' ? '#ffffff' : '#4caf50'}>
                    <path d="M10.6484 5.64648C10.8434 5.45148 11.1605 5.45148 11.3555 5.64648C11.5498 5.84137 11.5499 6.15766 11.3555 6.35254L7.35547 10.3525C7.25747 10.4495 7.12898 10.499 7.00098 10.499C6.87299 10.499 6.74545 10.4505 6.64746 10.3525L4.64746 8.35254C4.45247 8.15754 4.45248 7.84148 4.64746 7.64648C4.84246 7.45148 5.15949 7.45148 5.35449 7.64648L7 9.29199L10.6465 5.64648H10.6484Z"/>
                    <path fillRule="evenodd" clipRule="evenodd" d="M8 1C11.86 1 15 4.14 15 8C15 11.86 11.86 15 8 15C4.14 15 1 11.86 1 8C1 4.14 4.14 1 8 1ZM8 2C4.691 2 2 4.691 2 8C2 11.309 4.691 14 8 14C11.309 14 14 11.309 14 8C14 4.691 11.309 2 8 2Z"/>
                  </svg>
                </button>
              </Tooltip>
              <Tooltip content={currentResult === 'Failed' ? "Clear result" : "Mark as Failed"} position="left" isDarkTheme={isDarkTheme}>
                <button
                  style={{
                    ...restartButtonStyle,
                    background: currentResult === 'Failed'
                      ? '#f44336'
                      : (isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)"),
                    border: `1px solid ${isDarkTheme ? "#555" : "#ddd"}`,
                  }}
                  onClick={() => onResultChange(currentResult === 'Failed' ? '' : 'Failed')}
                  onMouseEnter={(e) => {
                    if (currentResult !== 'Failed') {
                      e.currentTarget.style.background = isDarkTheme ? "rgba(80, 80, 80, 0.8)" : "rgba(255, 255, 255, 1)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (currentResult !== 'Failed') {
                      e.currentTarget.style.background = isDarkTheme ? "rgba(60, 60, 60, 0.6)" : "rgba(255, 255, 255, 0.8)";
                    }
                  }}
                >
                  {/* Codicon error icon */}
                  <svg width="16" height="16" viewBox="0 0 16 16" xmlns="http://www.w3.org/2000/svg" fill={currentResult === 'Failed' ? '#ffffff' : '#f44336'}>
                    <path d="M8 1C4.14 1 1 4.14 1 8C1 11.86 4.14 15 8 15C11.86 15 15 11.86 15 8C15 4.14 11.86 1 8 1ZM8 14C4.691 14 2 11.309 2 8C2 4.691 4.691 2 8 2C11.309 2 14 4.691 14 8C14 11.309 11.309 14 8 14ZM10.854 5.854L8.708 8L10.854 10.146C11.049 10.341 11.049 10.658 10.854 10.853C10.756 10.951 10.628 10.999 10.5 10.999C10.372 10.999 10.244 10.95 10.146 10.853L8 8.707L5.854 10.853C5.756 10.951 5.628 10.999 5.5 10.999C5.372 10.999 5.244 10.95 5.146 10.853C4.951 10.658 4.951 10.341 5.146 10.146L7.292 8L5.146 5.854C4.951 5.659 4.951 5.342 5.146 5.147C5.341 4.952 5.658 4.952 5.853 5.147L7.999 7.293L10.145 5.147C10.34 4.952 10.657 4.952 10.852 5.147C11.047 5.342 11.047 5.659 10.852 5.854H10.854Z"/>
                  </svg>
                </button>
              </Tooltip>
            </>
          )}
        </div>
      </div>
    </div>
  );
};