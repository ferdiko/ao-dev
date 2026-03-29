export interface GraphNode {
    id: string;
    step_id?: number;
    input: string;
    output: string;
    stack_trace: string;
    label: string;
    position?: { x: number; y: number };
    border_color?: string;
    model?: string;
    node_kind?: 'llm' | 'mcp' | 'tool' | string;
    prior_status?: string | null;
    prior_count?: number | null;
    attachments?: any[];
}

export interface PriorRetrievalRecord {
    run_id: string;
    node_uuid: string;
    status: string;
    retrieval_context: string;
    inherited_prior_ids: string[];
    applied_priors: Array<{
        id: string;
        name?: string;
        summary?: string;
        content?: string;
        path?: string;
    }>;
    rendered_priors_block: string;
    injection_anchor?: { key?: string } | null;
    model?: string | null;
    timeout_ms?: number | null;
    latency_ms?: number | null;
    warning_message?: string | null;
    error_message?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
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
    run_id: string;
    status: string;
    timestamp?: string;
    color_preview?: string[];
    name?: string;
    result?: string;
    notes?: string;
    log?: string;
    version_date?: string;
}

export interface PriorSummary {
    id: string;
    name: string;
    summary: string;
}

export interface WorkflowRunDetailsPanelProps {
  runName?: string;
  result?: string;
  notes?: string;
  log?: string;
  codeVersion?: string;
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
