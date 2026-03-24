export interface GraphNode {
    id: string;
    input: string;
    output: string;
    stack_trace: string;
    label: string;
    position?: { x: number; y: number };
    border_color?: string;
    attachments?: any[];
}

export interface GraphEdge {
    id: string;
    source: string;
    target: string;
    type?: string;
    sourceHandle?: string;
    targetHandle?: string;
}

export interface Point {
    x: number;
    y: number;
}

export interface BoundingBox {
    x: number;
    y: number;
    width: number;
    height: number;
}

export interface RoutedEdge extends GraphEdge {
    points: Point[];
    sourceHandle: string;
    targetHandle: string;
}

export interface Message {
    type: string;
    payload?: any;
}

export interface NodeUpdateMessage extends Message {
    type: 'updateNode';
    payload: {
        nodeId: string;
        field: keyof GraphNode;
        value: string;
    };
}

export interface PopoverAction {
    id: string;
    label: string;
    icon?: string;
}

export interface GraphData {
    nodes: GraphNode[];
    edges: GraphEdge[];
}

export interface ProcessInfo {
    session_id: string;
    status: string;
    timestamp?: string;
    color_preview?: string[];
    run_name?: string;
    result?: string;
    notes?: string;
    log?: string;
    version_date?: string;
}

export interface LessonSummary {
    id: string;
    name: string;
    summary: string;
}

export interface WorkflowRunDetailsPanelProps {
  runName?: string;
  result?: string;
  notes?: string;
  log?: string;
  codeHash?: string;
  onOpenInTab?: () => void;
  messageSender?: import('./MessageSender').MessageSender;
}

//LayoutEngine
export interface LayerInfo {
  layer: number;
  visualLayers: string[][];
  nodes: LayoutNode[];
}

export interface BandInfo {
  name: string;
  x: number;
  side: 'left' | 'right';
  level: number;
  color?: string;
}

export interface GraphLayout {
  positions: Map<string, { x: number; y: number }>;
  edges: RoutedEdge[];
  width: number;
  height: number;
}

export interface RoutedEdge extends GraphEdge {
  points: Point[];
  sourceHandle: string;
  targetHandle: string;
  band?: string;
  type: 'direct' | 'band';
  color?: string;
}

export interface LayoutNode {
  id: string;
  label: string;
  parents: string[];
  children: string[];
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  layer?: number;
  visualLayer?: number;
  band?: string;
}
