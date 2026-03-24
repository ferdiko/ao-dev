import { LayerInfo } from '../core/types';

export interface LayoutConfig {
  nodeWidth: number;
  nodeHeight: number;
  layerSpacing: number;
  nodeSpacing: number;
}

export function calculateVisualLayers(layers: LayerInfo[], containerWidth: number, cfg: LayoutConfig): LayerInfo[] {
  const { nodeWidth, nodeHeight, nodeSpacing, layerSpacing } = cfg;
  const maxNodesPerRow = Math.max(1, Math.floor((containerWidth - nodeSpacing) / (nodeWidth + nodeSpacing)));
  const isSingleColumn = maxNodesPerRow === 1;
  const maxNodesPerVisualLayer = isSingleColumn ? 1 : Math.min(5, maxNodesPerRow);
  let mobileYOffset = nodeSpacing;
  let cumulativeY = 0;
  layers.forEach(layer => {
    const nodes = layer.nodes;
    const visualLayers: string[][] = [];
    const numVisualLayers = Math.ceil(nodes.length / maxNodesPerVisualLayer);
    for (let i = 0; i < nodes.length; i += maxNodesPerVisualLayer) {
      const vlNodes = nodes.slice(i, i + maxNodesPerVisualLayer);
      visualLayers.push(vlNodes.map(n => n.id));
      vlNodes.forEach((node, idx) => {
        node.visualLayer = Math.floor(i / maxNodesPerVisualLayer);
        if (isSingleColumn) {
          const leftPadding = 30;
            node.x = leftPadding + (containerWidth - leftPadding - nodeWidth) / 2;
            node.y = mobileYOffset;
            mobileYOffset += nodeHeight + 40;
        } else {
          const totalNodesInVisualLayer = vlNodes.length;
          const totalWidth = totalNodesInVisualLayer * nodeWidth + (totalNodesInVisualLayer - 1) * nodeSpacing;
          const xOffset = Math.max(nodeSpacing, (containerWidth - totalWidth) / 2);
          node.x = xOffset + idx * (nodeWidth + nodeSpacing);
          node.y = cumulativeY + node.visualLayer! * (nodeHeight + 20);
        }
        node.width = nodeWidth; node.height = nodeHeight;
      });
    }
    layer.visualLayers = visualLayers;
    if (!isSingleColumn) {
      const spaceUsedByThisLayer = numVisualLayers * (nodeHeight + 20) - 20;
      cumulativeY += spaceUsedByThisLayer + layerSpacing - (nodeHeight + 20);
    }
    if (isSingleColumn && nodes.length > 0) mobileYOffset += 20;
  });
  return layers;
}
