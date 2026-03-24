// src/webview/components/CustomNode.tsx
import React, { useEffect, useRef, useState } from 'react';
import { Handle, Position, NodeProps } from 'reactflow';
import { GraphNode } from '../../types';
import { NodePopover } from './NodePopover';
import { LabelEditor } from '../LabelEditor';
import { NODE_WIDTH, NODE_HEIGHT, NODE_BORDER_WIDTH } from '../../utils/layoutConstants';
import { MessageSender } from '../../types/MessageSender';

// Define handle offset constants for consistency
const SIDE_HANDLE_OFFSET = 15; // pixels from center
const HANDLE_TARGET_POSITION = 50 - SIDE_HANDLE_OFFSET; // 35% from top
const HANDLE_SOURCE_POSITION = 50 + SIDE_HANDLE_OFFSET; // 65% from top

// Label truncation
const MAX_LABEL_LENGTH = 20;

function truncateLabel(label: string): string {
  if (label.length > MAX_LABEL_LENGTH) {
    return label.slice(0, MAX_LABEL_LENGTH - 1) + "…";
  }
  return label;
}

interface CustomNodeData extends GraphNode {
  attachments: any;
  onUpdate: (nodeId: string, field: string, value: string) => void;
  session_id?: string;
  messageSender: MessageSender;
  isDarkTheme?: boolean;
  onHover?: (nodeId: string | null) => void;
  isHighlighted?: boolean;
}

export const CustomNode: React.FC<NodeProps<CustomNodeData>> = ({
  data,
  id,
  yPos,
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
          sessionId: data.session_id,
          field: "input",
          label: data.label || "Node",
          inputValue: data.input,
          outputValue: data.output,
        });
        break;
      case "editOutput":
        data.messageSender.send({
          type: "openNodeEditorTab",
          nodeId: id,
          sessionId: data.session_id,
          field: "output",
          label: data.label || "Node",
          inputValue: data.input,
          outputValue: data.output,
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
        height: NODE_HEIGHT,
        background: "var(--vscode-input-background)",
        border: `${NODE_BORDER_WIDTH}px solid var(--vscode-foreground, #CCCCCC)`,
        borderRadius: 8,
        padding: 2,
        position: "relative",
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
          fontSize: "11px",
          fontWeight: "600",
          fontFamily: "var(--vscode-font-family, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif)",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: "100%",
          opacity: isEditingLabel ? 0 : 1,
          color: "var(--vscode-foreground)",
          textAlign: "center",
          padding: "0 8px",
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}
        title={data.label}
      >
        {truncateLabel(data.label)}
      </div>
    </div>
  );
};

// Export handle positions for edge routing
export { HANDLE_TARGET_POSITION, HANDLE_SOURCE_POSITION };
