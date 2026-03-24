import { LayoutNode, Point } from '../core/types';
import { BAND_ENTRY_STAGGER_CLAMP } from '../../layoutConstants';

// Band path using explicit band X coordinate (mirrors original internal implementation)
export function createBandPath(source: LayoutNode, target: LayoutNode, bandX: number, side: 'left' | 'right', entryYOffset: number = 0, useCenteredTarget: boolean = false): Point[] {
  if (source.x == null || source.y == null || target.x == null || target.y == null) return [];
  const sourceX = source.x + (side === 'right' ? source.width! : 0);
  // Leave a bit below center for source side connections (distinguish as outgoing)
  const sourceY = source.y + source.height! * 0.65;
  const targetX = target.x + (side === 'right' ? target.width! : 0);
  
  // Use centered target position for single arrows, offset position for multiple
  let baseTargetY: number;
  if (useCenteredTarget) {
    // Center the arrow on the side of the node (50% height)
    baseTargetY = target.y + target.height! * 0.5;
  } else {
    // Enter a bit above center for target side connections (distinguish as incoming)
    baseTargetY = target.y + target.height! * 0.35;
  }
  
  const clampedOffset = Math.max(-BAND_ENTRY_STAGGER_CLAMP, Math.min(BAND_ENTRY_STAGGER_CLAMP, entryYOffset));
  const targetY = baseTargetY + clampedOffset;
  return [
    { x: sourceX, y: sourceY },
    { x: bandX, y: sourceY },
    { x: bandX, y: targetY },
    { x: targetX, y: targetY }
  ];
}

export function createBandPathWithHorizontalConnector(source: LayoutNode, target: LayoutNode, bandX: number, side: 'left' | 'right', children: LayoutNode[], entryYOffset: number = 0, useCenteredTarget: boolean = false): Point[] {
  if (source.x == null || source.y == null || target.x == null || target.y == null) return [];
  const sourceX = source.x + (side === 'right' ? source.width! : 0);
  const sourceY = source.y + source.height! * 0.65;
  if (!children.length) return createBandPath(source, target, bandX, side, entryYOffset, useCenteredTarget);
  const minChildY = Math.min(...children.filter(c => c && c.y != null).map(c => c.y!));
  const connectorY = (isFinite(minChildY) ? minChildY : sourceY) - 20;
  const targetCenterX = target.x + target.width! / 2;
  const clampedOffset = Math.max(-BAND_ENTRY_STAGGER_CLAMP, Math.min(BAND_ENTRY_STAGGER_CLAMP, entryYOffset));
  
  // Use centered target position for single arrows
  let targetY: number;
  if (useCenteredTarget) {
    // Center the arrow on the top of the node (50% height) for horizontal connectors
    targetY = target.y + target.height! * 0.5 + clampedOffset;
  } else {
    // Use original top connection for multiple arrows
    targetY = target.y + clampedOffset;
  }
  
  return [
    { x: sourceX, y: sourceY },
    { x: bandX, y: sourceY },
    { x: bandX, y: connectorY },
    { x: targetCenterX, y: connectorY },
    { x: targetCenterX, y: targetY }
  ];
}
