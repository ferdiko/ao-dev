import { LayoutNode, LayerInfo } from '../core/types';

export function wouldDirectLineCrossNodes(source: LayoutNode, target: LayoutNode, allNodes: LayoutNode[]): boolean {
  const sourceX = source.x! + source.width! / 2;
  const sourceY = source.y! + source.height!;
  const targetX = target.x! + target.width! / 2;
  const targetY = target.y!;
  return allNodes.some(node => {
    if (node.id === source.id || node.id === target.id) return false;
    if (node.y! <= sourceY || node.y! + node.height! >= targetY) return false;
    const nodeLeft = node.x!, nodeRight = node.x! + node.width!, nodeTop = node.y!, nodeBottom = node.y! + node.height!;
    const lineXAtNodeTop = sourceX + (targetX - sourceX) * (nodeTop - sourceY) / (targetY - sourceY);
    const lineXAtNodeBottom = sourceX + (targetX - sourceX) * (nodeBottom - sourceY) / (targetY - sourceY);
    const lineMinX = Math.min(lineXAtNodeTop, lineXAtNodeBottom);
    const lineMaxX = Math.max(lineXAtNodeTop, lineXAtNodeBottom);
    return !(lineMaxX < nodeLeft || lineMinX > nodeRight);
  });
}

export function hasNodesBetweenInVisualLayers(source: LayoutNode, target: LayoutNode, allNodes: LayoutNode[], layerSpacing: number): boolean {
  const sourceBottom = source.y! + source.height!;
  const targetTop = target.y!;
  const expectedSpacing = layerSpacing;
  const actualSpacing = targetTop - sourceBottom;
  if (actualSpacing > expectedSpacing * 1.5) return true;
  return allNodes.some(node => {
    if (node.id === source.id || node.id === target.id) return false;
    return node.y! > sourceBottom && node.y! + node.height! < targetTop;
  });
}

export function applyCenterBandCascade(layers: LayerInfo[], containerWidth: number, nodeWidth: number, nodeHeight: number, nodeSpacing: number, layerSpacing: number): void {
  const rowStep = nodeHeight + 20;

  const allNodes = layers.flatMap(l => l.nodes);

  // Match bandsCalc needsBand logic (single column vs wide screen)
  const needsBand = (node: any): boolean => {
    if (!node?.children?.length) return false;
    const maxNodesPerRow = Math.max(1, Math.floor((containerWidth - nodeSpacing) / (nodeWidth + nodeSpacing)));
    const isSingleColumn = maxNodesPerRow === 1;

    const hasSkipLayer = node.children.some((cid: string) => {
      const child = allNodes.find(n => n.id === cid);
      return child && child.layer !== (node.layer! + 1);
    });

    let directCross = false;
    directCross = node.children.some((cid: string) => {
      const child = allNodes.find(n => n.id === cid);
      if (!child || child.layer !== (node.layer! + 1)) return false;
      if (isSingleColumn) {
        const sourceBottom = node.y! + node.height!;
        const targetTop = child.y!;
        const between = allNodes.filter((n: any) => n.y! > sourceBottom && (n.y! + n.height!) < targetTop);
        return between.length > 0;
      }
      return wouldDirectLineCrossNodes(node, child, allNodes) || hasNodesBetweenInVisualLayers(node, child, allNodes, layerSpacing);
    });

    if (isSingleColumn) return hasSkipLayer || directCross || node.children.length > 1;
    return hasSkipLayer || directCross; // wide screen
  };

  const centerAlignRow = (rowNodes: any[]) => {
    const count = rowNodes.length;
    const totalWidth = count * nodeWidth + Math.max(0, count - 1) * nodeSpacing;
    const x0 = Math.max(nodeSpacing, (containerWidth - totalWidth) / 2);
    rowNodes.forEach((n, i) => { n.x = x0 + i * (nodeWidth + nodeSpacing); });
  };

  // Group nodes of a logical layer into visual rows by actual Y proximity
  const groupRowsByY = (nodes: any[], eps = 0.5): any[][] => {
    const rows: any[][] = [];
    const sorted = [...nodes].sort((a, b) => (a.y! - b.y!));
    for (const n of sorted) {
      const row = rows.find(r => Math.abs(r[0].y! - n.y!) <= eps);
      if (row) row.push(n); else rows.push([n]);
    }
    rows.forEach(r => r.sort((a, b) => (a.x! - b.x!)));
    return rows;
  };

  const hasMultipleDirectChildren = (node: any): boolean => {
    if (!node?.children?.length) return false;
    let count = 0;
    for (const cid of node.children) {
      const child = allNodes.find(n => n.id === cid);
      if (child && child.layer === node.layer! + 1) count++;
      if (count >= 2) return true;
    }
    return false;
  };

  layers.forEach((layer, idx) => {
    const ln = layer.nodes || [];
    if (ln.length < 3) return;

    // Establish base top Y and initial row count
    const originalTopY = Math.min(...ln.map(n => n.y!));
    let initialRows = groupRowsByY(ln).length;

    let changed = true;
    let guard = 0;
    const MAX_ITER = 10;
    while (changed && guard++ < MAX_ITER) {
      changed = false;
      const rows = groupRowsByY(ln);
      const toDrop: any[] = [];
      rows.forEach(rowNodes => {
        if (rowNodes.length < 3) return;
        const centralNodes = rowNodes.slice(1, rowNodes.length - 1);
        centralNodes.forEach((node: any) => {
          if (needsBand(node) || hasMultipleDirectChildren(node)) toDrop.push(node);
        });
      });

      if (toDrop.length === 0) break;

      // Move selected nodes down by one rowStep
      const dropSet = new Set(toDrop.map(n => n.id));
      ln.forEach(n => { if (dropSet.has(n.id)) n.y = (n.y ?? originalTopY) + rowStep; });

      // Rebuild rows by Y and re-center
      const updatedRows = groupRowsByY(ln);
      updatedRows.forEach((rowNodes, i) => {
        centerAlignRow(rowNodes);
        rowNodes.forEach(n => { n.y = originalTopY + i * rowStep; n.visualLayer = i; });
      });

      // Update layer.visualLayers for downstream consumers
      layer.visualLayers = updatedRows.map(r => r.map(n => n.id!));

      changed = true;
    }

    // Compute final row count and shift subsequent layers accordingly
    const finalRows = groupRowsByY(ln).length;
    const addedRows = Math.max(0, finalRows - initialRows);
    if (addedRows > 0) {
      const yDelta = addedRows * rowStep;
      for (let j = idx + 1; j < layers.length; j++) {
        layers[j].nodes.forEach(n => { if (typeof n.y === 'number') n.y += yDelta; });
      }
    }
  });
}
