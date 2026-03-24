// CustomEdge.tsx
import React from 'react';
import { EdgeProps, getSmoothStepPath } from 'reactflow';
import { Point } from '../../types';

interface CustomEdgeData {
  points?: Point[];
  isHighlighted?: boolean;
}

export const CustomEdge: React.FC<EdgeProps<CustomEdgeData>> = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  data,
}) => {
  let d: string;

  if (data?.points && data.points.length >= 2) {
    // force‐snap endpoints to the real handle centers
    const pts = [
      { x: data.points[0].x, y: data.points[0].y },
      ...data.points.slice(1, -1),
      {
        x: data.points[data.points.length - 1].x,
        y: data.points[data.points.length - 1].y,
      },
    ];

    d = pts.reduce((acc, p, i) => (i === 0 ? `M ${p.x},${p.y}` : `${acc} L ${p.x},${p.y}`), '');
  } else {
    // fallback to the built-in smooth path
    [d] = getSmoothStepPath({
      sourceX,
      sourceY,
      targetX,
      targetY,
      sourcePosition,
      targetPosition,
      borderRadius: 8,
    });
  }

  const defaultStroke = 'var(--vscode-foreground, #CCCCCC)';
  const isHighlighted = data?.isHighlighted ?? false;
  const highlightColor = '#43884e';

  const markerId = `arrow-${id}`;

  return (
    <svg style={{ overflow: 'visible', position: 'absolute' }}>
      <defs>
        <marker
          id={markerId}
          markerWidth="6"
          markerHeight="6"
          refX="6"
          refY="3"
          orient="auto"
          markerUnits="userSpaceOnUse"
        >
          <polygon
            points="0,0 6,3 0,6"
            fill={isHighlighted ? highlightColor : defaultStroke}
            stroke="none"
          />
        </marker>
      </defs>
      {/* Main edge path */}
      <path
        id={id}
        className="react-flow__edge-path"
        d={d}
        markerEnd={`url(#${markerId})`}
        style={{
          stroke: isHighlighted ? highlightColor : defaultStroke,
          strokeWidth: isHighlighted ? 3 : 1,
          fill: 'none',
        }}
      />
    </svg>
  );
};
