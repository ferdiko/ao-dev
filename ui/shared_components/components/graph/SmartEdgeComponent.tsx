// src/webview/components/CustomAvoidanceEdge.tsx
import React from 'react';
import { EdgeProps, useNodes } from 'reactflow';

import { NODE_WIDTH, NODE_HEIGHT } from '../../utils/layoutConstants';
const NODE_PADDING = 40;
const ROUTING_CLEARANCE = 30; // Space for routing around obstacles

interface Point {
    x: number;
    y: number;
}

interface NodeBounds {
    left: number;
    right: number;
    top: number;
    bottom: number;
    centerX: number;
    centerY: number;
    id: string;
}

const CustomAvoidanceEdge: React.FC<EdgeProps> = (props) => {
    const {
        id,
        sourceX,
        sourceY,
        targetX,
        targetY,
        style = {},
        markerEnd,
        markerStart,
    } = props;

    const nodes = useNodes();

    // Get node bounds with padding for collision detection
    const getNodeBounds = (): NodeBounds[] => {
        return nodes
            .filter(node => node.position)
            .map(node => ({
                left: node.position!.x - NODE_PADDING,
                right: node.position!.x + NODE_WIDTH + NODE_PADDING,
                top: node.position!.y - NODE_PADDING,
                bottom: node.position!.y + NODE_HEIGHT + NODE_PADDING,
                centerX: node.position!.x + NODE_WIDTH / 2,
                centerY: node.position!.y + NODE_HEIGHT / 2,
                id: node.id
            }));
    };

    // Check if a line segment intersects any node bounds
    const lineIntersectsNodes = (x1: number, y1: number, x2: number, y2: number, nodeBounds: NodeBounds[]): boolean => {
        const minX = Math.min(x1, x2);
        const maxX = Math.max(x1, x2);
        const minY = Math.min(y1, y2);
        const maxY = Math.max(y1, y2);

        return nodeBounds.some(bounds =>
            bounds.left <= maxX && bounds.right >= minX &&
            bounds.top <= maxY && bounds.bottom >= minY
        );
    };

    // Find a clear horizontal routing level between two Y coordinates
    const findClearHorizontalLevel = (startY: number, endY: number, nodeBounds: NodeBounds[]): number => {
        const minY = Math.min(startY, endY);
        const maxY = Math.max(startY, endY);
        
        // Try routing at the midpoint first
        const midY = (startY + endY) / 2;
        if (!nodeBounds.some(bounds => bounds.top <= midY && bounds.bottom >= midY)) {
            return midY;
        }

        // Try below the lowest node in the area
        const lowestNode = Math.max(...nodeBounds
            .filter(bounds => bounds.top <= maxY && bounds.bottom >= minY)
            .map(bounds => bounds.bottom));
        
        return lowestNode + ROUTING_CLEARANCE;
    };

    // Find a clear vertical routing position to the left or right
    const findClearVerticalPosition = (preferLeft: boolean, nodeBounds: NodeBounds[]): number => {
        if (preferLeft) {
            // Find leftmost obstacle and go further left
            const leftmost = Math.min(...nodeBounds.map(bounds => bounds.left));
            return leftmost - ROUTING_CLEARANCE;
        } else {
            // Find rightmost obstacle and go further right
            const rightmost = Math.max(...nodeBounds.map(bounds => bounds.right));
            return rightmost + ROUTING_CLEARANCE;
        }
    };

    const generateSystematicPath = (): string => {
        const nodeBounds = getNodeBounds();
        
        // Calculate connection points
        const sourceBottom: Point = { x: sourceX, y: sourceY + NODE_HEIGHT / 2 };
        const targetTop: Point = { x: targetX, y: targetY - NODE_HEIGHT / 2 };
        const sourceLeft: Point = { x: sourceX - NODE_WIDTH / 2, y: sourceY };
        const sourceRight: Point = { x: sourceX + NODE_WIDTH / 2, y: sourceY };
        const targetLeft: Point = { x: targetX - NODE_WIDTH / 2, y: targetY };
        const targetRight: Point = { x: targetX + NODE_WIDTH / 2, y: targetY };

        // CASE 1: Try straight line from bottom to top (0 corners)
        if (!lineIntersectsNodes(sourceBottom.x, sourceBottom.y, targetTop.x, targetTop.y, nodeBounds)) {
            return `M ${sourceBottom.x},${sourceBottom.y} L ${targetTop.x},${targetTop.y}`;
        }

        // CASE 2: Bottom to top with 2 corners (down, horizontal, down)
        const routingY = findClearHorizontalLevel(sourceBottom.y, targetTop.y, nodeBounds);
        
        // Check if we can route horizontally at this level
        if (!lineIntersectsNodes(sourceBottom.x, routingY, targetTop.x, routingY, nodeBounds)) {
            return `M ${sourceBottom.x},${sourceBottom.y} L ${sourceBottom.x},${routingY} L ${targetTop.x},${routingY} L ${targetTop.x},${targetTop.y}`;
        }

        // Find obstacles in the horizontal routing area
        const horizontalObstacles = nodeBounds.filter(bounds => 
            bounds.top <= routingY && bounds.bottom >= routingY
        );

        // Try routing around obstacles horizontally
        if (horizontalObstacles.length > 0) {
            const obstacleLeft = Math.min(...horizontalObstacles.map(b => b.left));
            const obstacleRight = Math.max(...horizontalObstacles.map(b => b.right));
            
            // Determine if we should route left or right around obstacles
            const sourceTargetMidX = (sourceBottom.x + targetTop.x) / 2;
            const obstacleMidX = (obstacleLeft + obstacleRight) / 2;
            const routeLeft = sourceTargetMidX < obstacleMidX;
            
            const avoidanceX = routeLeft ? 
                obstacleLeft - ROUTING_CLEARANCE : 
                obstacleRight + ROUTING_CLEARANCE;
            
            // Check if this avoidance route is clear
            if (!lineIntersectsNodes(sourceBottom.x, sourceBottom.y, sourceBottom.x, routingY, nodeBounds) &&
                !lineIntersectsNodes(sourceBottom.x, routingY, avoidanceX, routingY, nodeBounds) &&
                !lineIntersectsNodes(avoidanceX, routingY, targetTop.x, routingY, nodeBounds) &&
                !lineIntersectsNodes(targetTop.x, routingY, targetTop.x, targetTop.y, nodeBounds)) {
                
                return `M ${sourceBottom.x},${sourceBottom.y} L ${sourceBottom.x},${routingY} L ${avoidanceX},${routingY} L ${targetTop.x},${routingY} L ${targetTop.x},${targetTop.y}`;
            }
        }

        // CASE 3: Side to side routing (3 corners)
        // Determine which side to use based on spatial relationship
        const useLeftSide = sourceX > targetX; // If target is to the left, use left side
        
        const sourceHandle = useLeftSide ? sourceLeft : sourceRight;
        const targetHandle = useLeftSide ? targetLeft : targetRight;
        
        // Find clear vertical routing position
        const verticalX = findClearVerticalPosition(useLeftSide, nodeBounds);
        
        // Find clear horizontal routing level
        const horizontalY = findClearHorizontalLevel(sourceHandle.y, targetHandle.y, nodeBounds);
        
        // Create the 3-corner path: side → vertical → horizontal → side
        return `M ${sourceHandle.x},${sourceHandle.y} L ${verticalX},${sourceHandle.y} L ${verticalX},${horizontalY} L ${targetHandle.x},${horizontalY} L ${targetHandle.x},${targetHandle.y}`;
    };

    const edgePath = generateSystematicPath();

    return (
        <path
            id={id}
            style={{
                stroke: '#555',
                strokeWidth: 2,
                fill: 'none',
                ...style
            }}
            className="react-flow__edge-path"
            d={edgePath}
            markerEnd={markerEnd}
            markerStart={markerStart}
        />
    );
};

export default CustomAvoidanceEdge;