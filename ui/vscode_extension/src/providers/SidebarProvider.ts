import * as vscode from 'vscode';
import * as fs from 'fs';
import { GraphTabProvider } from './GraphTabProvider';
import { PythonServerClient } from './PythonServerClient';
import { SovaraDBClient } from './SovaraDBClient';
import { configManager } from './ConfigManager';
export class SidebarProvider implements vscode.WebviewViewProvider {
    public static readonly viewType = 'sovara.graphView';
    private _view?: vscode.WebviewView;
    private _graphTabProvider?: GraphTabProvider;
    private _pendingMessages: any[] = [];
    private _pythonClient: PythonServerClient | null = null;
    private _messageHandler?: (msg: any) => void;
    private _windowStateListener?: vscode.Disposable;
    // The Python server connection is deferred until the webview sends 'ready'.
    // Buffering is needed to ensure no messages are lost if the server sends messages before the webview is ready.

    constructor(private readonly _extensionUri: vscode.Uri, private readonly _context: vscode.ExtensionContext) {
        // Set up window focus detection to request runs when VS Code regains focus
        this._windowStateListener = vscode.window.onDidChangeWindowState((state) => {
            if (state.focused && this._pythonClient && this._view) {
                // Window regained focus - request fresh run list from server
                this._pythonClient.httpGet('/ui/runs').then(r => this._view?.webview.postMessage(r));
            }
        });
    }



    public setGraphTabProvider(provider: GraphTabProvider): void {
        this._graphTabProvider = provider;
    }

    // Robustly show or reveal the webview
    public showWebview() {
        if (!this._view || (this._view as any)._disposed) {
            // Create new webview view
            vscode.commands.executeCommand('workbench.view.extension.sovara-sidebar');
            // The view will be resolved via resolveWebviewView
        } else {
            this._view.show?.(true);
        }
    }


    public handleEditDialogSave(value: string, context: { nodeId: string; field: string; run_id?: string; attachments?: any }): void {
        this._view?.webview.postMessage({
            type: 'updateNode',
            payload: {
                nodeId: context.nodeId,
                field: context.field,
                value,
                run_id: context.run_id,
            }
        });
    }

    private _applyUiConfig(config: { config_path?: string; priors_url?: string } | undefined): void {
        if (!config) {
            return;
        }

        if (config.config_path) {
            try {
                configManager.setConfigPath(config.config_path);

                // Set up config forwarding to webview
                configManager.onConfigChange((cfg) => {
                    if (this._view) {
                        this._view.webview.postMessage({
                            type: 'configUpdate',
                            detail: cfg
                        });
                    }
                });
            } catch (e) {
                console.warn('[SidebarProvider] Error setting config_path:', e);
            }
        }

        if (config.priors_url) {
            this._pythonClient?.setPriorsUrl(config.priors_url);
            SovaraDBClient.init(config.priors_url);
        }
    }


    public resolveWebviewView(
        webviewView: vscode.WebviewView,
_context: vscode.WebviewViewResolveContext,
        _token: vscode.CancellationToken,
    ) {
        this._view = webviewView;

        // Clean up reference when disposed
        webviewView.onDidDispose(() => {
            this._view = undefined;
        });

        // Request fresh run list when the webview becomes visible
        webviewView.onDidChangeVisibility(() => {
            if (webviewView.visible && this._pythonClient) {
                this._pythonClient.httpGet('/ui/runs').then(r => this._view?.webview.postMessage(r));
            }
        });

        // Flush any pending messages to the webview
        this._pendingMessages.forEach(msg => {
            if (this._view) {
                this._view.webview.postMessage(msg);
            }
        });
        this._pendingMessages = [];

        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                this._extensionUri
            ]
        };

        webviewView.webview.html = this._getHtmlForWebview(webviewView.webview);
        this._sendCurrentTheme();
        vscode.window.onDidChangeActiveColorTheme(() => {
            this._sendCurrentTheme();
        });

        // Handle messages from the webview
        webviewView.webview.onDidReceiveMessage(data => {
            switch (data.type) {
                case 'restart':
                    if (!data.run_id) {
                        console.error('Restart message missing run_id!');
                        return;
                    }
                    this._pythonClient?.httpPost('/ui/restart', { run_id: data.run_id });
                    break;
                case 'open_log_tab_side_by_side':
                    console.warn('NotesLogTabProvider not available');
                    break;
                case 'update_node':
                    this._pythonClient?.httpPost('/ui/update-node', {
                        run_id: data.run_id, node_uuid: data.node_uuid,
                        field: data.field, value: data.value,
                    });
                    break;
                case 'edit_input':
                    this._pythonClient?.httpPost('/ui/edit-input', {
                        run_id: data.run_id, node_uuid: data.node_uuid, value: data.value,
                    });
                    break;
                case 'edit_output':
                    this._pythonClient?.httpPost('/ui/edit-output', {
                        run_id: data.run_id, node_uuid: data.node_uuid, value: data.value,
                    });
                    break;
                case 'get_graph':
                    if (data.run_id) {
                        this._pythonClient?.httpGet(`/ui/graph/${data.run_id}`).then(r => this._view?.webview.postMessage(r));
                    }
                    break;
                case 'erase':
                    this._pythonClient?.httpPost('/ui/erase', { run_id: data.run_id });
                    break;
                case 'get_more_runs':
                    this._pythonClient?.httpGet(`/ui/runs/more?offset=${data.offset || 0}`).then(r => this._view?.webview.postMessage(r));
                    break;
                case 'get_run_detail':
                    if (data.run_id) {
                        this._pythonClient?.httpGet(`/ui/run/${data.run_id}`).then(r => this._view?.webview.postMessage(r));
                    }
                    break;
                case 'ready':
                    // Webview is ready - now connect to the Python server and set up message forwarding
                    if (!this._pythonClient) {
                        this._pythonClient = PythonServerClient.getInstance();
                        this._pythonClient.ensureConnected(); // async but don't await - webview is ready
                        // Request run list on every connection (including reconnections after server restart)
                        this._pythonClient.onConnection(() => {
                            this._pythonClient?.getUiConfig()
                                .then((config) => this._applyUiConfig(config))
                                .catch((err) => console.warn('[SidebarProvider] Error fetching /ui/config:', err));
                            this._pythonClient?.httpGet('/ui/runs').then(r => this._view?.webview.postMessage(r));
                        });
                        // Create message handler and store reference for cleanup
                        this._messageHandler = (msg) => {
                            // Keep websocket bootstrap as a compatibility fallback.
                            if (msg.type === 'run_id') {
                                this._applyUiConfig(msg);
                            }
                            if (this._view) {
                                this._view.webview.postMessage(msg);
                            } else {
                                this._pendingMessages.push(msg);
                            }
                        };
                        // Forward all messages from the Python server to the webview, buffer if not ready
                        this._pythonClient.onMessage(this._messageHandler);
                        this._pythonClient.startServerIfNeeded();
                    }

                    this._pythonClient?.getUiConfig()
                        .then((config) => this._applyUiConfig(config))
                        .catch((err) => console.warn('[SidebarProvider] Error fetching /ui/config:', err));

                    // Request runs after Python client is set up
                    if (this._pythonClient) {
                        this._pythonClient.httpGet('/ui/runs').then(r => this._view?.webview.postMessage(r));
                    }
                    break;
                case 'navigateToCode':
                    // Handle code navigation
                    const { filePath, line } = this._parseStackTrace(data.payload.stack_trace);
                    if (filePath && line) {
                        vscode.workspace.openTextDocument(filePath).then(document => {
                            vscode.window.showTextDocument(document, {
                                selection: new vscode.Range(line - 1, 0, line - 1, 0)
                            });
                        });
                    }
                    break;
                case 'openGraphTab':
                    if (this._graphTabProvider && data.payload.run) {
                        this._graphTabProvider.createOrShowGraphTab(data.payload.run);
                    } else {
                        console.warn('[GraphViewProvider] No GraphTabProvider available or missing run data');
                    }
                    break;
                case 'openPriorsTab':
                    if (this._graphTabProvider) {
                        this._graphTabProvider.createOrShowPriorsTab();
                    } else {
                        console.warn('[GraphViewProvider] No GraphTabProvider available for priors');
                    }
                    break;
                case 'openPriorEditorTab':
                    if (this._graphTabProvider && data.priorId) {
                        this._graphTabProvider.createOrShowPriorEditorTab(data.priorId, data.priorName || 'Prior');
                    } else {
                        console.warn('[GraphViewProvider] No GraphTabProvider available for prior editor or missing priorId');
                    }
                    break;
                case 'closePriorEditorTab':
                    if (this._graphTabProvider) {
                        this._graphTabProvider.closePriorEditorTab();
                    }
                    break;
                case 'requestRunRefresh':
                    // RunsView has mounted and is ready to display data - request run list
                    if (this._pythonClient) {
                        this._pythonClient.httpGet('/ui/runs').then(r => this._view?.webview.postMessage(r));
                    }
                    break;
            }
        });
    }

    private _sendCurrentTheme() {
        const isDark = vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.Dark;
        this._view?.webview.postMessage({
            type: 'vscode-theme-change',
            payload: {
                theme: isDark ? 'vscode-dark' : 'vscode-light',
            },
        });
    }

    private _getHtmlForWebview(webview: vscode.Webview) {
        const path = require('path');
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const codiconsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'codicons', 'codicon.css'));
        const templatePath = path.join(
            this._extensionUri.fsPath,
            'src',
            'webview',
            'templates',
            'graphView.html'
        );
        let html = fs.readFileSync(templatePath, 'utf8');
        
        // Set up ConfigManager bridge to webview
        const configBridge = `
            window.configManager = {
                currentConfig: null,
                onConfigChange: function(callback) {
                    window.addEventListener('configUpdate', function(event) {
                        window.configManager.currentConfig = event.detail;
                        callback(event.detail);
                    });
                },
                getCurrentConfig: function() {
                    return window.configManager.currentConfig;
                }
            };
        `;
        
        console.log('🚀 Injecting config into webview');
        
        html = html.replace('const vscode = acquireVsCodeApi();', 
            `${configBridge}\n        const vscode = acquireVsCodeApi();`);
        html = html.replace(/{{scriptUri}}/g, scriptUri.toString());
        html = html.replace(/{{codiconsUri}}/g, codiconsUri.toString());
        return html;
    }

    private _parseStackTrace(stackTrace: string): { filePath: string | undefined; line: number | undefined } {
        // Parse Python stack trace format: File "/path/to/file.py", line 42, in function_name
        // Returns the first (most recent user code) file and line number
        if (!stackTrace) {
            return { filePath: undefined, line: undefined };
        }

        // Match Python traceback format
        const match = stackTrace.match(/File "([^"]+)", line (\d+)/);
        if (match) {
            const [, filePath, lineStr] = match;
            return {
                filePath,
                line: parseInt(lineStr, 10)
            };
        }
        return { filePath: undefined, line: undefined };
    }

    public dispose(): void {
        // Clean up message listener
        if (this._pythonClient && this._messageHandler) {
            this._pythonClient.removeMessageListener(this._messageHandler);
            this._messageHandler = undefined;
        }
        // Clean up window state listener
        if (this._windowStateListener) {
            this._windowStateListener.dispose();
            this._windowStateListener = undefined;
        }
        // Clean up SovaraDBClient
        SovaraDBClient.getInstance()?.dispose();
        // Clean up is handled by ConfigManager
    }
}
