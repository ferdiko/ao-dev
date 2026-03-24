import { GraphNode, GraphEdge, LayerInfo, GraphLayout, LayoutNode, RoutedEdge } from '../types';
import { applyCenterBandCascade } from './layout/logic/collisions';
import { convertToLayoutNodes } from './layout/core/convert';
import { calculateLogicalLayers } from './layout/logic/layers';
import { calculateVisualLayers } from './layout/logic/visualLayers';
import { calculateEdges } from './layout/logic/edges';
import { calculateDimensions } from './layout/logic/dimensions';
import { NODE_WIDTH, NODE_HEIGHT, LAYER_SPACING, STACK_LAYER_SPACING, NODE_SPACING, BAND_SPACING, LAYOUT_MODE } from './layoutConstants';
import { calculateBands as calculateBandsMod } from './layout/logic/bandsCalc';
import { calculateStackLayout } from './layout/logic/stackLayout';

export class LayoutEngine {
  private nodeWidth = NODE_WIDTH;
  private nodeHeight = NODE_HEIGHT;
  private layerSpacing = LAYER_SPACING;
  private nodeSpacing = NODE_SPACING;
  private bandSpacing = BAND_SPACING;

  public layoutGraph(nodes: GraphNode[], edges: GraphEdge[], containerWidth?: number): GraphLayout {
    // Set default container width
    const width = containerWidth || 800; // Default fallback

    // Convert workflow-extension data to LayoutEngine format
    const layoutNodes = this.convertToLayoutEngineFormat(nodes, edges);

    // Branch based on layout mode
    if (LAYOUT_MODE === 'stack') {
      return this.layoutStack(layoutNodes, width);
    }
    return this.layoutGrid(layoutNodes, width);
  }

  private layoutStack(layoutNodes: LayoutNode[], containerWidth: number): GraphLayout {
    // Stack layout: single column, chronological order
    const stackSpacing = STACK_LAYER_SPACING;
    const { layers, bands } = calculateStackLayout(layoutNodes, {
      nodeWidth: this.nodeWidth,
      nodeHeight: this.nodeHeight,
      layerSpacing: stackSpacing,
      bandSpacing: this.bandSpacing,
      containerWidth
    });

    const routedEdges = calculateEdges(layoutNodes, bands, containerWidth, stackSpacing, this.nodeHeight, this.nodeSpacing);
    const { width: totalWidth, height } = calculateDimensions(layers, bands);

    return this.buildResult(layoutNodes, routedEdges, totalWidth, height);
  }

  private layoutGrid(layoutNodes: LayoutNode[], containerWidth: number): GraphLayout {
    // Grid layout: multi-column, parent-grouped layers
    const layers = this.calculateLayers(layoutNodes);
    const visualLayers = calculateVisualLayers(layers, containerWidth, {
      nodeWidth: this.nodeWidth,
      nodeHeight: this.nodeHeight,
      layerSpacing: this.layerSpacing,
      nodeSpacing: this.nodeSpacing
    });

    // Cascade drop for internal nodes with skip-layer children
    applyCenterBandCascade(visualLayers, containerWidth, this.nodeWidth, this.nodeHeight, this.nodeSpacing, this.layerSpacing);

    const bands = calculateBandsMod(layoutNodes, visualLayers, {
      nodeWidth: this.nodeWidth,
      nodeHeight: this.nodeHeight,
      nodeSpacing: this.nodeSpacing,
      layerSpacing: this.layerSpacing,
      bandSpacing: this.bandSpacing,
      containerWidth
    });
    const routedEdges = calculateEdges(layoutNodes, bands, containerWidth, this.layerSpacing, this.nodeHeight, this.nodeSpacing);
    const { width: totalWidth, height } = calculateDimensions(visualLayers, bands);

    return this.buildResult(layoutNodes, routedEdges, totalWidth, height);
  }

  private buildResult(layoutNodes: LayoutNode[], routedEdges: RoutedEdge[], totalWidth: number, height: number): GraphLayout {
    // Convert back to workflow-extension format
    const positions = new Map<string, { x: number; y: number }>();
    layoutNodes.forEach(node => {
      // Validate node position before adding
      if (node.x !== undefined && node.y !== undefined &&
        !isNaN(node.x) && !isNaN(node.y) &&
        isFinite(node.x) && isFinite(node.y)) {
        positions.set(node.id, { x: node.x, y: node.y });
      } else {
        // Fallback position if calculation failed
        console.warn(`Invalid position for node ${node.id}:`, { x: node.x, y: node.y });
        positions.set(node.id, { x: 0, y: 0 });
      }
    });

    return {
      positions,
      edges: routedEdges,
      width: totalWidth,
      height
    };
  }

  private convertToLayoutEngineFormat(nodes: GraphNode[], edges: GraphEdge[]): LayoutNode[] {
    return convertToLayoutNodes(nodes, edges);
  }
  private calculateLayers(nodes: LayoutNode[]): LayerInfo[] {
    return calculateLogicalLayers(nodes);
  }
}