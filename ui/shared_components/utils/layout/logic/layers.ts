import { LayoutNode, LayerInfo } from '../core/types';

export function calculateLogicalLayers(nodes: LayoutNode[]): LayerInfo[] {
  const nodesWithIndex = nodes.map((node, index) => ({ node, originalIndex: index }));
  const layerMap = new Map<string, { node: LayoutNode, originalIndex: number }[]>();
  nodesWithIndex.forEach(({ node, originalIndex }) => {
    const parentKey = [...node.parents].sort().join(',');
    if (!layerMap.has(parentKey)) layerMap.set(parentKey, []);
    layerMap.get(parentKey)!.push({ node, originalIndex });
  });
  const layers: LayerInfo[] = [];
  let layerIndex = 0;
  const sortedParentKeys = Array.from(layerMap.keys()).sort((a,b) => layerMap.get(a)![0].originalIndex - layerMap.get(b)![0].originalIndex);
  sortedParentKeys.forEach(key => {
    const arr = layerMap.get(key)!;
    arr.sort((a,b)=> a.originalIndex - b.originalIndex);
    const layerNodes = arr.map(x => x.node);
    layerNodes.forEach(n => { n.layer = layerIndex; });
    layers.push({ layer: layerIndex, visualLayers: [], nodes: layerNodes });
    layerIndex++;
  });
  return layers;
}
