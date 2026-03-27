import { GraphNode } from '../types';

declare const vscode: any;

export function sendMessage(message: any) {
    vscode.postMessage(message);
}

export function sendNodeUpdate(nodeId: string, field: keyof GraphNode, value: string, run_id?: string) {
    const msg = {
        type: 'updateNode',
        nodeId,
        field,
        value,
        run_id
    };
    sendMessage(msg);
}

export function sendReady() {
    vscode.postMessage({
        type: 'ready'
    });
}

export function sendNavigateToCode(stack_trace: string) {
    vscode.postMessage({
        type: 'navigateToCode',
        payload: { stack_trace }
    });
}

export function sendReset() {
    sendMessage({ type: 'reset', id: Math.floor(Math.random() * 100000) });
}

// Send a get_graph message to the backend for a given run_id
export function sendGetGraph(run_id: string) {
    sendMessage({ type: 'get_graph', run_id });
}
