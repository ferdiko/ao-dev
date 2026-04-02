// src/webview/components/CustomNode.tsx
import React, { useEffect, useRef, useState } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { GraphNode } from '../../types';
import { NodePopover } from './NodePopover';
import { LabelEditor } from '../LabelEditor';
import {
  NODE_WIDTH,
  NODE_HEIGHT,
  NODE_BORDER_WIDTH,
  NODE_PRIOR_HEADER_HEIGHT,
  getGraphNodeHeight,
} from '../../utils/layoutConstants';
import { MessageSender } from '../../types/MessageSender';

// Define handle offset constants for consistency
const SIDE_HANDLE_OFFSET = 15; // pixels from center
const HANDLE_TARGET_POSITION = 50 - SIDE_HANDLE_OFFSET; // 35% from top
const HANDLE_SOURCE_POSITION = 50 + SIDE_HANDLE_OFFSET; // 65% from top

interface CustomNodeData extends GraphNode {
  attachments: any;
  onUpdate: (nodeId: string, field: string, value: string) => void;
  run_id?: string;
  messageSender: MessageSender;
  isDarkTheme?: boolean;
  onHover?: (nodeId: string | null) => void;
  isHighlighted?: boolean;
}

export const CustomNode: React.FC<NodeProps<CustomNodeData>> = ({
  data,
  id,
}) => {
  const [showPopover, setShowPopover] = useState(false);
  const [isEditingLabel, setIsEditingLabel] = useState(false);
  const [isHovered, setIsHovered] = useState(false);
  const leaveTimeoutRef = useRef<number | null>(null);

  const handleStyle: React.CSSProperties = {
    width: 8,
    height: 8,
    border: '2px solid #555',
    background: '#fff',
    opacity: 0, // Make handles invisible
  };

  // Helper to create side handle styles with vertical offset
  const createSideHandleStyle = (position: number): React.CSSProperties => ({
    ...handleStyle,
    top: `${position}%`,
  });

  const leftTargetStyle = createSideHandleStyle(HANDLE_TARGET_POSITION);
  const leftSourceStyle = createSideHandleStyle(HANDLE_SOURCE_POSITION);
  const rightTargetStyle = createSideHandleStyle(HANDLE_TARGET_POSITION);
  const rightSourceStyle = createSideHandleStyle(HANDLE_SOURCE_POSITION);

  const handleAction = async (action: string) => {
    switch (action) {
      case "editInput":
        data.messageSender.send({
          type: "openNodeEditorTab",
          nodeId: id,
          runId: data.run_id,
          field: "input",
          label: data.label || "Node",
          inputValue: data.input,
          outputValue: data.output,
          nodeKind: data.node_kind,
          priorCount: data.prior_count,
        });
        break;
      case "editOutput":
        data.messageSender.send({
          type: "openNodeEditorTab",
          nodeId: id,
          runId: data.run_id,
          field: "output",
          label: data.label || "Node",
          inputValue: data.input,
          outputValue: data.output,
          nodeKind: data.node_kind,
          priorCount: data.prior_count,
        });
        break;
      case "changeLabel":
        setIsEditingLabel(true);
        break;
      // case "seeInCode":
      //   data.messageSender.send({
      //     type: "navigateToCode",
      //     payload: { stack_trace: data.stack_trace }
      //   });
      //   break;
    }
  };

  const handleLabelSave = (newLabel: string) => {
    data.onUpdate(id, "label", newLabel);
    setIsEditingLabel(false);
  };  

  const isDarkTheme = data.isDarkTheme ?? false;
  const priorCount = typeof data.prior_count === 'number' ? data.prior_count : 0;
  const showPriorHeader = priorCount > 0;
  const totalNodeHeight = getGraphNodeHeight(data.prior_count);
  const priorHeaderLabel = `${priorCount} prior${priorCount === 1 ? '' : 's'}`;
  const priorHeaderStyle: React.CSSProperties = {
    background: isDarkTheme ? 'rgba(56, 139, 253, 0.18)' : 'rgba(9, 105, 218, 0.14)',
    color: isDarkTheme ? '#9ecbff' : '#0550ae',
    borderBottom: isDarkTheme ? '1px solid rgba(88, 166, 255, 0.28)' : '1px solid rgba(9, 105, 218, 0.22)',
  };
  // const isHighlighted = data.isHighlighted ?? false;

  const nodeRef = useRef<HTMLDivElement>(null);
  const [popoverCoords, setPopoverCoords] = useState<{top: number, left: number} | null>(null);

  useEffect(() => {
    if (showPopover && nodeRef.current) {
      const rect = nodeRef.current.getBoundingClientRect();
      // Position popover below the node, horizontally centered
      const top = rect.bottom + 8;
      const left = rect.left + (rect.width / 2);

      setPopoverCoords({ top, left });
    } else if (!showPopover) {
      setPopoverCoords(null);
    }
  }, [showPopover]);

  return (
    <div
      ref={nodeRef}
      style={{
        boxSizing: "border-box",
        width: NODE_WIDTH,
        height: totalNodeHeight,
        background: "var(--vscode-input-background)",
        border: `${NODE_BORDER_WIDTH}px solid var(--vscode-foreground, #CCCCCC)`,
        borderRadius: 8,
        position: "relative",
        overflow: "hidden",
        cursor: "pointer",
        filter: isHovered ? (isDarkTheme ? 'brightness(1.2)' : 'brightness(0.9)') : 'none',
        transition: 'filter 0.1s ease-out',
        // boxShadow: isHighlighted
        //   ? `0 0 8px 2px ${isDarkTheme ? 'rgba(255, 255, 255, 0.6)' : 'rgba(0, 0, 0, 0.4)'}`
        //   : 'none',
        // transition: 'box-shadow 0.15s ease-out',
      }}
      onClick={() => {
        setShowPopover(true);
      }}
      onMouseEnter={() => {
        setIsHovered(true);
        if (leaveTimeoutRef.current) {
          clearTimeout(leaveTimeoutRef.current);
          leaveTimeoutRef.current = null;
        }
        data.onHover?.(id);
      }}
      onMouseLeave={() => {
        setIsHovered(false);
        leaveTimeoutRef.current = window.setTimeout(() => {
          setShowPopover(false);
        }, 150);
        data.onHover?.(null);
      }}
    >
      {showPriorHeader && priorHeaderLabel && (
        <div
          style={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            height: NODE_PRIOR_HEADER_HEIGHT,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.02em',
            textTransform: 'uppercase',
            boxSizing: 'border-box',
            ...priorHeaderStyle,
            zIndex: 2,
          }}
          title={priorHeaderLabel}
        >
          {priorHeaderLabel}
        </div>
      )}
      {showPopover && !isEditingLabel && popoverCoords && (
        <NodePopover
          onAction={handleAction}
          onMouseEnter={() => {
            if (leaveTimeoutRef.current) {
              clearTimeout(leaveTimeoutRef.current);
              leaveTimeoutRef.current = null;
            }
            setShowPopover(true);
          }}
          onMouseLeave={() => setShowPopover(false)}
          position="below"
          top={popoverCoords.top}
          left={popoverCoords.left}
          isDarkTheme={isDarkTheme}
        />
      )}
      {isEditingLabel && (
        <LabelEditor
          initialValue={data.label}
          onSave={handleLabelSave}
          onCancel={() => setIsEditingLabel(false)}
        />
      )}
      <Handle
        type="target"
        position={Position.Top}
        id="top"
        style={handleStyle}
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="bottom"
        style={handleStyle}
      />

      {/* Side handles - offset positions */}
      <Handle
        type="target"
        position={Position.Left}
        id="left-target"
        style={leftTargetStyle}
      />
      <Handle
        type="source"
        position={Position.Left}
        id="left-source"
        style={leftSourceStyle}
      />
      <Handle
        type="target"
        position={Position.Right}
        id="right-target"
        style={rightTargetStyle}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right-source"
        style={rightSourceStyle}
      />

      {/* Centered side handles for single arrows */}
      <Handle
        type="target"
        position={Position.Left}
        id="left-center"
        style={{...handleStyle, top: '50%'}}
      />
      <Handle
        type="source"
        position={Position.Left}
        id="left-center-source"
        style={{...handleStyle, top: '50%'}}
      />
      <Handle
        type="target"
        position={Position.Right}
        id="right-center"
        style={{...handleStyle, top: '50%'}}
      />
      <Handle
        type="source"
        position={Position.Right}
        id="right-center-source"
        style={{...handleStyle, top: '50%'}}
      />

      {/* Label */}
      <div
        style={{
          position: 'absolute',
          top: showPriorHeader ? NODE_PRIOR_HEADER_HEIGHT : 0,
          left: 0,
          right: 0,
          bottom: 0,
          boxSizing: "border-box",
          padding: "6px 10px",
          zIndex: 1,
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          opacity: isEditingLabel ? 0 : 1,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "baseline",
            gap: 8,
            minWidth: 0,
          }}
        >
          <div
            style={{
              fontSize: "11px",
              fontWeight: 600,
              fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
              color: "var(--vscode-foreground)",
              flex: "1 1 auto",
              minWidth: 0,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={data.label}
          >
            {data.label}
          </div>
          {typeof data.step_id === "number" && (
            <div
              style={{
                fontSize: "9px",
                fontWeight: 500,
                fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
                color: "var(--vscode-descriptionForeground, var(--vscode-foreground))",
                opacity: 0.78,
                whiteSpace: "nowrap",
                flex: "0 0 auto",
                pointerEvents: "none",
              }}
              title={`Step ${data.step_id}`}
            >
              {`Step ${data.step_id}`}
            </div>
          )}
        </div>
        {data.raw_node_name && (
          <div
            style={{
              fontSize: "9px",
              fontWeight: 400,
              fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
              color: "var(--vscode-descriptionForeground, var(--vscode-foreground))",
              opacity: 0.7,
              marginTop: 1,
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
            title={data.raw_node_name}
          >
            {data.raw_node_name}
          </div>
        )}
        {!data.raw_node_name && <div style={{ height: 10, marginTop: 1 }} />}
      </div>
    </div>
  );
};

// Export handle positions for edge routing
export { HANDLE_TARGET_POSITION, HANDLE_SOURCE_POSITION };
