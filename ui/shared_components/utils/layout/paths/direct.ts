import { LayoutNode, Point } from '../core/types';

export function createDirectPath(source: LayoutNode, target: LayoutNode, nodeHeight: number): Point[] {
  const sourceX = source.x! + source.width! / 2;
  const sourceY = source.y! + source.height!;
  const targetX = target.x! + target.width! / 2;
  const targetY = target.y!;
  const horizontalTolerance = 10;
  if (Math.abs(sourceX - targetX) <= horizontalTolerance) {
    return [ { x: sourceX, y: sourceY }, { x: targetX, y: targetY } ];
  }
  const midY = sourceY + (targetY - sourceY) / 2;
  return [
    { x: sourceX, y: sourceY },
    { x: sourceX, y: midY },
    { x: targetX, y: midY },
    { x: targetX, y: targetY }
  ];
}
