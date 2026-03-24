import { LayerInfo, BandInfo } from '../core/types';

export function calculateDimensions(layers: LayerInfo[], bands: BandInfo[]): { width: number; height: number } {
  const allNodes = layers.flatMap(l => l.nodes);
  if (!allNodes.length) return { width: 800, height: 400 };
  const minNodeX = Math.min(...allNodes.map(n => n.x!));
  const maxNodeX = Math.max(...allNodes.map(n => n.x! + n.width!));
  const minNodeY = Math.min(...allNodes.map(n => n.y!));
  const maxNodeY = Math.max(...allNodes.map(n => n.y! + n.height!));
  const leftBands = bands.filter(b => b.side === 'left');
  const rightBands = bands.filter(b => b.side === 'right');
  const minBandX = leftBands.length ? Math.min(...leftBands.map(b => b.x)) : Infinity;
  const maxBandX = rightBands.length ? Math.max(...rightBands.map(b => b.x)) : -Infinity;
  const minX = Math.min(minNodeX, isFinite(minBandX) ? minBandX : minNodeX) - 20;
  const maxX = Math.max(maxNodeX, isFinite(maxBandX) ? maxBandX : maxNodeX) + 20;
  const width = Math.max(maxX - minX, 400);
  const height = Math.max(maxNodeY - minNodeY + 100, 300);
  return { width, height };
}
