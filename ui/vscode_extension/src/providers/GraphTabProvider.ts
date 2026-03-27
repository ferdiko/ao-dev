import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { PythonServerClient } from './PythonServerClient';
import { PlaybookClient } from './PlaybookClient';
import { ProcessInfo } from '@sovara/shared-components/types';
import { type DetectedDocument, getFileExtensionsForDocumentType, getMimeTypeForDocumentType } from '@sovara/shared-components/utils/documentDetection';

export class GraphTabProvider implements vscode.WebviewPanelSerializer {
    public static readonly viewType = 'sovara.graphTab';
    private _panels: Map<string, vscode.WebviewPanel> = new Map();
    private _pythonClient: PythonServerClient | null = null;
    private _sidebarProvider: { refreshLessons: () => void } | null = null;
    public setSidebarProvider(provider: { refreshLessons: () => void }): void {
        this._sidebarProvider = provider;
    }

    constructor(private readonly _extensionUri: vscode.Uri) {
        // Initialize Python client
        this._pythonClient = PythonServerClient.getInstance();
        this._pythonClient.ensureConnected(); // async but don't await in constructor
    }

    private get _iconPath(): vscode.Uri {
        return vscode.Uri.joinPath(this._extensionUri, 'dist', 'icon.png');
    }

    private async _ensurePriorsClient(): Promise<PlaybookClient | null> {
        let client = PlaybookClient.getInstance();
        if (client) {
            return client;
        }

        if (this._pythonClient) {
            try {
                await this._pythonClient.getUiConfig();
            } catch {
                // Defer to the existing error handling at the call site.
            }
        }

        const priorsUrl = this._pythonClient?.getPlaybookUrl();
        if (!priorsUrl) {
            return null;
        }

        return PlaybookClient.init(priorsUrl);
    }

    // ============================================================
    // Priors helpers — call PlaybookClient and post results to webview
    // ============================================================

    private async _handleFolderLs(panel: vscode.WebviewPanel, reqPath: string): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lesson_error', error: 'Priors server not configured' }); return; }
        try {
            const result = await client.fetchFolder(reqPath);
            if (result.error) { panel.webview.postMessage({ type: 'lesson_error', error: result.error || result.detail }); return; }
            panel.webview.postMessage({
                type: 'folder_ls_result',
                path: reqPath,
                folders: (result.folders || []).map((folder: any) => ({
                    ...folder,
                    lesson_count: folder.lesson_count ?? folder.prior_count ?? 0,
                })),
                lessons: result.priors || [],
                lesson_count: result.prior_count || 0,
            });
        } catch (e: any) { panel.webview.postMessage({ type: 'lesson_error', error: e.message }); }
    }

    private async _handleGetLesson(panel: vscode.WebviewPanel, lessonId: string): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lesson_error', error: 'Priors server not configured' }); return; }
        try {
            const result = await client.getLesson(lessonId);
            if (result.error) { panel.webview.postMessage({ type: 'lesson_error', error: result.error || result.detail }); return; }
            panel.webview.postMessage({ type: 'lesson_content', lesson: result });
        } catch (e: any) { panel.webview.postMessage({ type: 'lesson_error', error: e.message }); }
    }

    private async _handleGetLessons(panel: vscode.WebviewPanel): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lessons_list', lessons: [], error: 'Priors server not configured' }); return; }
        try {
            const result = await client.getLessonsList();
            if (result.error) { panel.webview.postMessage({ type: 'lessons_list', lessons: [], error: result.error }); return; }
            const lessons = Array.isArray(result) ? result : result.priors || [];
            panel.webview.postMessage({ type: 'lessons_list', lessons });
        } catch (e: any) { panel.webview.postMessage({ type: 'lessons_list', lessons: [], error: e.message }); }
    }

    private async _handleAddLesson(panel: vscode.WebviewPanel, data: any): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lesson_error', error: 'Priors server not configured' }); return; }
        try {
            const result = await client.createLesson(
                { name: data.name, summary: data.summary || '', content: data.content, path: data.path || '' },
                !!data.force,
            );
            if (result.status === 'rejected') {
                let reason = result.reason || 'Validation failed';
                if (result.hint) { reason += `\n\nHint: ${result.hint}`; }
                panel.webview.postMessage({ type: 'lesson_rejected', reason, severity: 'error', conflicting_lesson_ids: result.conflicting_prior_ids || [] });
            } else if (result.error) {
                panel.webview.postMessage({ type: 'lesson_error', error: result.error });
            } else if (result.status === 'created') {
                panel.webview.postMessage({
                    type: 'lesson_created',
                    lesson: result,
                    validation: result.validation ? {
                        ...result.validation,
                        conflicting_lesson_ids: result.validation.conflicting_prior_ids || [],
                    } : undefined,
                });
            } else {
                panel.webview.postMessage({ type: 'lesson_error', error: 'Unexpected server response' });
            }
        } catch (e: any) { panel.webview.postMessage({ type: 'lesson_error', error: e.message }); }
    }

    private async _handleUpdateLesson(panel: vscode.WebviewPanel, data: any): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lesson_error', error: 'Priors server not configured' }); return; }
        const lessonId = data.lesson_id;
        if (!lessonId) { panel.webview.postMessage({ type: 'lesson_error', error: 'Missing lesson_id' }); return; }
        const fields: any = {};
        for (const f of ['name', 'summary', 'content', 'path']) { if (data[f] !== undefined) { fields[f] = data[f]; } }
        try {
            const result = await client.updateLesson(lessonId, fields, !!data.force);
            if (result.status === 'rejected') {
                let reason = result.reason || 'Validation failed';
                if (result.hint) { reason += `\n\nHint: ${result.hint}`; }
                panel.webview.postMessage({ type: 'lesson_rejected', reason, severity: 'error', conflicting_lesson_ids: result.conflicting_prior_ids || [] });
            } else if (result.error) {
                panel.webview.postMessage({ type: 'lesson_error', error: result.error });
            } else if (result.status === 'updated') {
                panel.webview.postMessage({
                    type: 'lesson_updated',
                    lesson: result,
                    validation: result.validation ? {
                        ...result.validation,
                        conflicting_lesson_ids: result.validation.conflicting_prior_ids || [],
                    } : undefined,
                });
            } else {
                panel.webview.postMessage({ type: 'lesson_error', error: 'Unexpected server response' });
            }
        } catch (e: any) { panel.webview.postMessage({ type: 'lesson_error', error: e.message }); }
    }

    private async _handleDeleteLesson(panel: vscode.WebviewPanel, data: any): Promise<void> {
        const client = await this._ensurePriorsClient();
        if (!client) { panel.webview.postMessage({ type: 'lesson_error', error: 'Priors server not configured' }); return; }
        const lessonId = data.lesson_id;
        if (!lessonId) { panel.webview.postMessage({ type: 'lesson_error', error: 'Missing lesson_id' }); return; }
        try {
            const result = await client.deleteLesson(lessonId);
            if (result.error) {
                panel.webview.postMessage({ type: 'lesson_error', error: result.error });
            }
            // SSE event will trigger refresh in all panels
        } catch (e: any) { panel.webview.postMessage({ type: 'lesson_error', error: e.message }); }
    }

    // ============================================================
    // Wire PlaybookClient SSE events to a webview panel
    // ============================================================

    private _setupPlaybookEvents(panel: vscode.WebviewPanel): void {
        const client = PlaybookClient.getInstance();
        if (!client) { return; }

        const handler = () => {
            panel.webview.postMessage({ type: 'lessons_refresh' });
        };
        client.on('lesson_event', handler);
        panel.onDidDispose(() => { client.removeListener('lesson_event', handler); });
    }

    // ============================================================
    // Graph Tab
    // ============================================================

    public async createOrShowGraphTab(run: ProcessInfo): Promise<void> {
        const runId = run.run_id;

        // Check if we already have a panel for this run
        let panel = this._panels.get(runId);

        if (panel) {
            // Check if panel is disposed
            if ((panel as any)._disposed || (panel as any).disposed) {
                this._panels.delete(runId);
                panel = undefined;
            } else {
                // Panel exists and is not disposed, just reveal it
                panel.reveal();
                return;
            }
        }

        // Find an existing graph panel to determine which column to use
        let existingGraphColumn: vscode.ViewColumn | undefined;
        for (const [key, existingPanel] of this._panels.entries()) {
            // Check if this is a graph panel (run ID format, not 'lessons' or 'node-editor')
            if (key !== 'lessons' && key !== 'node-editor' && existingPanel.viewColumn) {
                existingGraphColumn = existingPanel.viewColumn;
                break;
            }
        }

        // If we have an existing graph panel, open in same column
        // If there's an active editor, open beside it; otherwise open in column One
        let columnToShowIn: vscode.ViewColumn;
        if (existingGraphColumn) {
            columnToShowIn = existingGraphColumn;
        } else if (vscode.window.activeTextEditor) {
            columnToShowIn = vscode.ViewColumn.Beside;
        } else {
            columnToShowIn = vscode.ViewColumn.One;
        }

        // Create new panel
        panel = vscode.window.createWebviewPanel(
            GraphTabProvider.viewType,
            `Graph: ${run.name || runId.substring(0, 8)}...`,
            columnToShowIn,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [
                    this._extensionUri,
                    vscode.Uri.joinPath(this._extensionUri, 'dist')
                ]
            }
        );

        // Set tab icon
        panel.iconPath = this._iconPath;

        // Set up the webview content
        panel.webview.html = this._getHtmlForWebview(panel.webview, runId);

        // Store panel reference
        this._panels.set(runId, panel);

        // Handle panel disposal
        panel.onDidDispose(() => {
            this._panels.delete(runId);
        }, null);

        // Handle messages from the webview
        panel.webview.onDidReceiveMessage(data => {

            switch (data.type) {
                case 'ready':
                    // Send initial data to the tab
                    panel.webview.postMessage({
                        type: 'init',
                        payload: {
                            run,
                            runId
                        }
                    });
                    // Ensure Python client is available
                    if (!this._pythonClient) {
                        this._pythonClient = PythonServerClient.getInstance();
                        this._pythonClient.ensureConnected(); // async but don't await
                    }
                    // Fetch initial data via HTTP and post to webview
                    if (this._pythonClient) {
                        this._pythonClient.httpGet(`/ui/graph/${runId}`).then(r => panel.webview.postMessage(r));
                        this._pythonClient.httpGet(`/ui/run/${runId}`).then(r => panel.webview.postMessage(r));
                        this._pythonClient.httpGet(`/ui/lessons-applied/${runId}`).then(r => panel.webview.postMessage(r));
                        this._pythonClient.httpGet('/ui/runs').then(r => panel.webview.postMessage(r));
                    } else {
                        console.error('[GraphTabProvider] Still no Python client available after getInstance()');
                    }
                    break;
                case 'restart':
                    this._pythonClient?.httpPost('/ui/restart', { run_id: runId });
                    break;
                case 'erase':
                    this._pythonClient?.httpPost('/ui/erase', { run_id: runId });
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
                case 'update_node':
                    this._pythonClient?.httpPost('/ui/update-node', {
                        run_id: data.run_id, node_uuid: data.node_uuid,
                        field: data.field, value: data.value,
                    });
                    break;
                case 'update_name':
                    this._pythonClient?.httpPost('/ui/update-run-name', {
                        run_id: data.run_id, name: data.name,
                    });
                    break;
                case 'update_result':
                    this._pythonClient?.httpPost('/ui/update-result', {
                        run_id: data.run_id, result: data.result,
                    });
                    break;
                case 'update_notes':
                    this._pythonClient?.httpPost('/ui/update-notes', {
                        run_id: data.run_id, notes: data.notes,
                    });
                    break;
                case 'navigateToCode':
                    const { filePath, line } = this._parseStackTrace(data.payload.stack_trace);
                    if (filePath && line) {
                        vscode.workspace.openTextDocument(filePath).then(document => {
                            vscode.window.showTextDocument(document, {
                                selection: new vscode.Range(line - 1, 0, line - 1, 0)
                            });
                        });
                    }
                    break;
                case 'updateTabTitle':
                    const { runId: titleRunId, title } = data.payload;
                    const targetPanel = this._panels.get(titleRunId);
                    if (targetPanel && title) {
                        targetPanel.title = `Graph: ${title}`;
                    }
                    break;
                case 'get_lessons':
                    this._handleGetLessons(panel);
                    break;
                case 'get_lesson':
                    this._handleGetLesson(panel, data.lesson_id);
                    break;
                case 'openLessonsTab':
                    // Open the lessons tab
                    this.createOrShowLessonsTab();
                    break;
                case 'openDocument':
                    this._handleOpenDocument(data.payload, panel);
                    break;
                case 'saveDocument':
                    this._handleSaveDocument(data.payload);
                    break;
                case 'pickReplacementDocument':
                    this._handlePickReplacementDocument(data.payload, panel);
                    break;
                case 'openNodeEditorTab':
                    this.createOrShowNodeEditorTab(
                        data.nodeId,
                        data.runId,
                        data.field,
                        data.label,
                        data.inputValue,
                        data.outputValue
                    );
                    break;
                case 'switchRun':
                    // Switch to a different run in the current tab
                    if (data.runId && this._pythonClient) {
                        // Update the run reference for message forwarding
                        const runRef = (panel as any)._runRef;
                        if (runRef) {
                            runRef.current = data.runId;
                        }
                        // Fetch data for the new run via HTTP
                        this._pythonClient.httpGet(`/ui/graph/${data.runId}`).then(r => panel.webview.postMessage(r));
                        this._pythonClient.httpGet(`/ui/run/${data.runId}`).then(r => panel.webview.postMessage(r));
                        this._pythonClient.httpGet(`/ui/lessons-applied/${data.runId}`).then(r => panel.webview.postMessage(r));
                        // Update tab title
                        if (data.run?.name) {
                            panel.title = `Graph: ${data.run.name}`;
                        }
                        // Update the panel's run mapping
                        this._panels.delete(runId);
                        this._panels.set(data.runId, panel);
                    }
                    break;
            }
        });

        // Set up message forwarding from Python server
        this._setupServerMessageForwarding(panel, runId);

        // Send theme info
        this._sendThemeToPanel(panel);
        vscode.window.onDidChangeActiveColorTheme(() => {
            this._sendThemeToPanel(panel);
        });

        // Only lock the editor group if we opened beside an existing editor
        // (i.e., we created a new split). Don't lock if it's the only tab.
        if (columnToShowIn === vscode.ViewColumn.Beside) {
            await vscode.commands.executeCommand('workbench.action.lockEditorGroup');
        }
    }

    // ============================================================
    // Priors Tab (uses PlaybookClient directly)
    // ============================================================

    public async createOrShowLessonsTab(): Promise<void> {
        const lessonsTabId = 'lessons';
        const columnToShowIn = vscode.window.activeTextEditor ?
            vscode.ViewColumn.Beside :
            vscode.ViewColumn.One;

        // Check if we already have a lessons panel
        let panel = this._panels.get(lessonsTabId);

        if (panel) {
            // Check if panel is disposed
            if ((panel as any)._disposed || (panel as any).disposed) {
                this._panels.delete(lessonsTabId);
                panel = undefined;
            } else {
                // Panel exists and is not disposed, just reveal it
                panel.reveal(columnToShowIn);
                return;
            }
        }

        // Create new panel for priors
        panel = vscode.window.createWebviewPanel(
            GraphTabProvider.viewType,
            'Priors',
            columnToShowIn,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [
                    this._extensionUri,
                    vscode.Uri.joinPath(this._extensionUri, 'dist')
                ]
            }
        );

        // Set tab icon
        panel.iconPath = this._iconPath;

        // Set up the webview content for lessons
        panel.webview.html = this._getHtmlForLessonsWebview(panel.webview);

        // Store panel reference
        this._panels.set(lessonsTabId, panel);

        // Handle panel disposal
        panel.onDidDispose(() => {
            this._panels.delete(lessonsTabId);
        }, null);

        // Handle messages from the webview
        panel.webview.onDidReceiveMessage(data => {
            switch (data.type) {
                case 'ready':
                    // Request root folder listing directly from the priors server
                    this._handleFolderLs(panel, '');
                    break;
                case 'folder_ls':
                    this._handleFolderLs(panel, data.path ?? '');
                    break;
                case 'add_lesson':
                    this._handleAddLesson(panel, data);
                    break;
                case 'update_lesson':
                    this._handleUpdateLesson(panel, data);
                    break;
                case 'delete_lesson':
                    this._handleDeleteLesson(panel, data);
                    break;
                case 'get_lesson':
                    this._handleGetLesson(panel, data.lesson_id);
                    break;
                case 'get_runs_for_lesson':
                    if (data.lesson_id && this._pythonClient) {
                        this._pythonClient.httpGet(`/ui/runs-for-lesson/${data.lesson_id}`)
                            .then(r => panel.webview.postMessage(r));
                    }
                    break;
                case 'navigateToRun':
                    // Navigate to a specific run's graph - handled by opening a new graph tab
                    if (data.runId) {
                        // We need to get the run info to open the graph tab
                        // For now, create a minimal run object
                        const run = {
                            run_id: data.runId,
                            name: data.runId.substring(0, 8) + '...',
                        };
                        this.createOrShowGraphTab(run as any);
                    }
                    break;
            }
        });

        // Wire PlaybookClient SSE events for real-time sync
        await this._ensurePriorsClient();
        this._setupPlaybookEvents(panel);

        // Send theme info
        this._sendThemeToPanel(panel);
        vscode.window.onDidChangeActiveColorTheme(() => {
            this._sendThemeToPanel(panel);
        });
    }

    // ============================================================
    // Node Editor Tab
    // ============================================================

    public async createOrShowNodeEditorTab(
        nodeId: string,
        runId: string,
        field: 'input' | 'output',
        label: string,
        inputValue: any,
        outputValue: any
    ): Promise<void> {
        // Single reusable tab for all node editors (not per-node)
        const tabId = 'node-editor';
        // Open in column 1 (the main/non-locked group where code files are)
        const columnToShowIn = vscode.ViewColumn.One;

        // Check if we already have a node editor panel
        let panel = this._panels.get(tabId);

        if (panel) {
            // Check if panel is disposed
            if ((panel as any)._disposed || (panel as any).disposed) {
                this._panels.delete(tabId);
                panel = undefined;
            } else {
                // Panel exists - send message to update its content with new node data
                panel.webview.postMessage({
                    type: 'updateNodeData',
                    payload: {
                        nodeId,
                        runId,
                        field,
                        label,
                        inputValue,
                        outputValue
                    }
                });
                panel.title = `Edit: ${label || nodeId.substring(0, 8)}`;
                // Reveal in its current column (don't move it)
                panel.reveal();
                return;
            }
        }

        // Create new panel for node editor
        panel = vscode.window.createWebviewPanel(
            GraphTabProvider.viewType,
            `Edit: ${label || nodeId.substring(0, 8)}`,
            columnToShowIn,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                enableFindWidget: true,
                localResourceRoots: [
                    this._extensionUri,
                    vscode.Uri.joinPath(this._extensionUri, 'dist')
                ]
            }
        );

        // Set tab icon
        panel.iconPath = this._iconPath;

        // Set up the webview content for node editor
        panel.webview.html = this._getHtmlForNodeEditorWebview(
            panel.webview,
            nodeId,
            runId,
            field,
            label,
            inputValue,
            outputValue
        );

        // Store panel reference
        this._panels.set(tabId, panel);

        // Handle panel disposal
        panel.onDidDispose(() => {
            this._panels.delete(tabId);
        }, null);

        // Handle messages from the webview
        panel.webview.onDidReceiveMessage(data => {
            switch (data.type) {
                case 'ready':
                    // Send init data to the webview
                    panel.webview.postMessage({
                        type: 'init',
                        payload: {
                            nodeId,
                            runId,
                            field,
                            label,
                            inputValue,
                            outputValue
                        }
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
                case 'openDocument':
                    this._handleOpenDocument(data.payload, panel);
                    break;
                case 'saveDocument':
                    this._handleSaveDocument(data.payload);
                    break;
                case 'pickReplacementDocument':
                    this._handlePickReplacementDocument(data.payload, panel);
                    break;
                case 'closeTab':
                    panel.dispose();
                    break;
            }
        });

        // Send theme info
        this._sendThemeToPanel(panel);
        vscode.window.onDidChangeActiveColorTheme(() => {
            this._sendThemeToPanel(panel);
        });
    }

    private _getHtmlForNodeEditorWebview(
        webview: vscode.Webview,
        nodeId: string,
        runId: string,
        field: string,
        label: string,
        inputValue: any,
        outputValue: any
    ): string {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const codiconsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'codicons', 'codicon.css'));

        // Escape values for embedding in HTML
        // inputValue and outputValue are already JSON strings, so we just need to escape for HTML embedding
        const escapeForHtml = (str: string) => str
            .replace(/\\/g, '\\\\')
            .replace(/'/g, "\\'")
            .replace(/</g, '\\u003c')
            .replace(/>/g, '\\u003e')
            .replace(/\n/g, '\\n')
            .replace(/\r/g, '\\r');
        const escapedInputValue = escapeForHtml(inputValue || '{}');
        const escapedOutputValue = escapeForHtml(outputValue || '{}');
        const escapedLabel = label.replace(/'/g, "\\'").replace(/</g, '&lt;').replace(/>/g, '&gt;');

        const html = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Edit: ${escapedLabel}</title>
    <link rel="stylesheet" href="${codiconsUri}">
    <style>
        html, body {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            background-color: var(--vscode-editor-background);
            color: var(--vscode-foreground);
        }
        #node-editor-root {
            width: 100%;
            height: 100%;
        }
    </style>
    <script>
        window.process = {
            env: {},
            platform: 'browser',
            version: '',
            versions: {},
            type: 'renderer',
            arch: 'x64'
        };
    </script>
</head>
<body>
    <div id="node-editor-root"></div>
    <script>
        const vscode = acquireVsCodeApi();
        window.vscode = vscode;
        window.nodeEditorContext = {
            nodeId: '${nodeId}',
            runId: '${runId}',
            field: '${field}',
            label: '${escapedLabel}',
            inputValue: '${escapedInputValue}',
            outputValue: '${escapedOutputValue}'
        };
    </script>
    <script src="${scriptUri}"></script>
</body>
</html>
        `;

        return html;
    }

    // ============================================================
    // Server message forwarding (graph data, run lists, etc.)
    // ============================================================

    private _setupServerMessageForwarding(panel: vscode.WebviewPanel, runId: string): void {
        if (!this._pythonClient) {
            console.warn('[GraphTabProvider] No Python client available for message forwarding');
            return;
        }

        // Use an object to hold current runId so it can be updated when switching runs
        const runRef = { current: runId };
        (panel as any)._runRef = runRef; // Store reference on panel for later updates

        const messageHandler = (msg: any) => {
            // Forward relevant messages to this specific tab
            if (msg.run_id === runRef.current || !msg.run_id) {
                panel.webview.postMessage(msg);
            }
        };

        this._pythonClient.onMessage(messageHandler);

        // Clean up when panel is disposed
        panel.onDidDispose(() => {
            if (this._pythonClient) {
                this._pythonClient.removeMessageListener(messageHandler);
            }
        });
    }

    private _sendThemeToPanel(panel: vscode.WebviewPanel): void {
        const isDark = vscode.window.activeColorTheme.kind === vscode.ColorThemeKind.Dark;
        panel.webview.postMessage({
            type: 'vscode-theme-change',
            payload: {
                theme: isDark ? 'vscode-dark' : 'vscode-light',
            },
        });
    }

    private _getHtmlForWebview(webview: vscode.Webview, runId: string): string {
        const path = require('path');
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const codiconsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'codicons', 'codicon.css'));

        const templatePath = path.join(
            this._extensionUri.fsPath,
            'src',
            'webview',
            'templates',
            'graphTab.html'
        );

        let html: string;
        try {
            html = fs.readFileSync(templatePath, 'utf8');
        } catch (error) {
            // Fallback to inline HTML if template file doesn't exist yet
            html = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Graph Tab</title>
    <link rel="stylesheet" href="{{codiconsUri}}">
    <script>
        window.process = {
            env: {},
            platform: 'browser',
            version: '',
            versions: {},
            type: 'renderer',
            arch: 'x64'
        };
    </script>
</head>
<body>
    <div id="graph-tab-root"></div>
    <script>
        const vscode = acquireVsCodeApi();
        window.vscode = vscode;
        window.runId = '${runId}';
    </script>
    <script src="{{scriptUri}}"></script>
</body>
</html>
            `;
        }

        html = html.replace(/{{scriptUri}}/g, scriptUri.toString());
        html = html.replace(/{{codiconsUri}}/g, codiconsUri.toString());
        html = html.replace(/{{runId}}/g, runId);

        return html;
    }

    private _getHtmlForLessonsWebview(webview: vscode.Webview): string {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const codiconsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'codicons', 'codicon.css'));

        const html = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Priors</title>
    <link rel="stylesheet" href="${codiconsUri}">
    <script>
        window.process = {
            env: {},
            platform: 'browser',
            version: '',
            versions: {},
            type: 'renderer',
            arch: 'x64'
        };
    </script>
</head>
<body>
    <div id="lessons-root"></div>
    <script>
        const vscode = acquireVsCodeApi();
        window.vscode = vscode;
        window.isLessonsView = true;
    </script>
    <script src="${scriptUri}"></script>
</body>
</html>
        `;

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

    private async _handleOpenDocument(payload: { data: string; fileType: string; mimeType: string; documentKey?: string; fileName?: string }, panel: vscode.WebviewPanel): Promise<void> {
        const { data, fileType, documentKey, fileName } = payload;

        // Whitelist of file types we'll open with system default app
        const openableTypes = ['pdf', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'docx', 'xlsx', 'pptx'];
        const shouldOpen = openableTypes.includes(fileType);

        try {
            // Save to temp file
            const tempDir = os.tmpdir();
            const safeFileName = (fileName || `sovara-preview-${Date.now()}.${fileType}`).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
            const tempPath = path.join(tempDir, safeFileName);

            const buffer = Buffer.from(data, 'base64');
            fs.writeFileSync(tempPath, buffer);

            // Open with system default app if whitelisted
            if (shouldOpen) {
                const uri = vscode.Uri.file(tempPath);
                await vscode.env.openExternal(uri);
            }

            // Send path back to webview
            panel.webview.postMessage({
                type: 'documentOpened',
                payload: { path: tempPath, documentKey }
            });
        } catch (error) {
            console.error('[GraphTabProvider] Failed to open document:', error);
            vscode.window.showErrorMessage(`Failed to open document: ${error}`);
        }
    }

    private async _handleSaveDocument(payload: { data: string; fileType: string; mimeType: string; fileName?: string }): Promise<void> {
        const { data, fileType, fileName } = payload;

        try {
            const suggestedName = (fileName || `document.${fileType}`).replace(/[<>:"/\\|?*\x00-\x1F]/g, '_');
            const targetUri = await vscode.window.showSaveDialog({
                defaultUri: vscode.Uri.file(path.join(os.homedir(), suggestedName)),
                filters: {
                    [fileType.toUpperCase()]: [fileType],
                },
            });

            if (!targetUri) {
                return;
            }

            const buffer = Buffer.from(data, 'base64');
            fs.writeFileSync(targetUri.fsPath, buffer);
        } catch (error) {
            console.error('[GraphTabProvider] Failed to save document:', error);
            vscode.window.showErrorMessage(`Failed to save document: ${error}`);
        }
    }

    private async _handlePickReplacementDocument(
        payload: { requestId: string; expectedType: DetectedDocument['type'] },
        panel: vscode.WebviewPanel,
    ): Promise<void> {
        const { requestId, expectedType } = payload;

        try {
            const fileExtensions = getFileExtensionsForDocumentType(expectedType);
            const selectedUris = await vscode.window.showOpenDialog({
                canSelectMany: false,
                openLabel: 'Replace File',
                filters: {
                    [expectedType.toUpperCase()]: fileExtensions,
                },
            });

            const selectedUri = selectedUris?.[0];
            if (!selectedUri) {
                panel.webview.postMessage({
                    type: 'replacementDocumentPicked',
                    payload: { requestId, cancelled: true },
                });
                return;
            }

            const buffer = fs.readFileSync(selectedUri.fsPath);
            panel.webview.postMessage({
                type: 'replacementDocumentPicked',
                payload: {
                    requestId,
                    data: buffer.toString('base64'),
                    fileName: path.basename(selectedUri.fsPath),
                    mimeType: getMimeTypeForDocumentType(expectedType),
                },
            });
        } catch (error) {
            console.error('[GraphTabProvider] Failed to pick replacement document:', error);
            panel.webview.postMessage({
                type: 'replacementDocumentPicked',
                payload: { requestId, cancelled: true },
            });
        }
    }

    // ============================================================
    // Prior Editor Tab (uses PlaybookClient directly)
    // ============================================================

    public closeLessonEditorTab(): void {
        const panel = this._panels.get('lesson-editor');
        if (panel && !(panel as any)._disposed && !(panel as any).disposed) {
            panel.dispose();
        }
        this._panels.delete('lesson-editor');
    }

    public async createOrShowLessonEditorTab(
        lessonId: string,
        lessonName: string
    ): Promise<void> {
        // Single reusable tab for lesson editor (updates content when switching lessons)
        const tabId = 'lesson-editor';
        const columnToShowIn = vscode.ViewColumn.One;

        // Check if we already have a lesson editor panel
        let panel = this._panels.get(tabId);

        if (panel) {
            // Check if panel is disposed
            if ((panel as any)._disposed || (panel as any).disposed) {
                this._panels.delete(tabId);
                panel = undefined;
            } else {
                // Panel exists - send message to update its content with new lesson data
                panel.webview.postMessage({
                    type: 'updateLessonData',
                    payload: { lessonId, lessonName }
                });
                panel.title = `Lesson: ${lessonName.substring(0, 20)}${lessonName.length > 20 ? '...' : ''}`;
                panel.reveal();
                return;
            }
        }

        // Create new panel for lesson editor
        panel = vscode.window.createWebviewPanel(
            GraphTabProvider.viewType,
            `Lesson: ${lessonName.substring(0, 20)}${lessonName.length > 20 ? '...' : ''}`,
            columnToShowIn,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [
                    this._extensionUri,
                    vscode.Uri.joinPath(this._extensionUri, 'dist')
                ]
            }
        );

        // Set tab icon
        panel.iconPath = this._iconPath;

        // Set up the webview content for lesson editor
        panel.webview.html = this._getHtmlForLessonEditorWebview(panel.webview, lessonId, lessonName);

        // Store panel reference
        this._panels.set(tabId, panel);

        // Handle panel disposal
        panel.onDidDispose(() => {
            this._panels.delete(tabId);
        }, null);

        // Handle messages from the webview
        panel.webview.onDidReceiveMessage(data => {
            switch (data.type) {
                case 'ready':
                    // Request lessons list for dropdown directly from the priors server
                    this._handleGetLessons(panel);
                    break;
                case 'lessonUpdated':
                    // Notify sidebar to refresh lessons list
                    this._sidebarProvider?.refreshLessons();
                    break;
                case 'get_lessons':
                    this._handleGetLessons(panel);
                    break;
                case 'get_lesson':
                    this._handleGetLesson(panel, data.lesson_id);
                    break;
                case 'add_lesson':
                    this._handleAddLesson(panel, data);
                    break;
                case 'update_lesson':
                    this._handleUpdateLesson(panel, data);
                    break;
            }
        });

        // Wire PlaybookClient SSE events for real-time sync
        await this._ensurePriorsClient();
        this._setupPlaybookEvents(panel);

        // Send theme info
        this._sendThemeToPanel(panel);
        vscode.window.onDidChangeActiveColorTheme(() => {
            this._sendThemeToPanel(panel);
        });
    }

    private _getHtmlForLessonEditorWebview(
        webview: vscode.Webview,
        lessonId: string,
        lessonName: string
    ): string {
        const scriptUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'webview.js'));
        const codiconsUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'dist', 'codicons', 'codicon.css'));

        const escapedLessonId = lessonId.replace(/'/g, "\\'");
        const escapedLessonName = lessonName.replace(/'/g, "\\'").replace(/</g, '&lt;').replace(/>/g, '&gt;');

        const html = `
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Lesson Editor</title>
    <link rel="stylesheet" href="${codiconsUri}">
    <style>
        body {
            margin: 0;
            padding: 0;
            overflow: hidden;
        }
    </style>
    <script>
        window.process = {
            env: {},
            platform: 'browser',
            version: '',
            versions: {},
            type: 'renderer',
            arch: 'x64'
        };
    </script>
</head>
<body>
    <div id="lesson-editor-root"></div>
    <script>
        const vscode = acquireVsCodeApi();
        window.vscode = vscode;
        window.lessonEditorContext = {
            lessonId: '${escapedLessonId}',
            lessonName: '${escapedLessonName}'
        };
    </script>
    <script src="${scriptUri}"></script>
</body>
</html>
        `;

        return html;
    }

    public async deserializeWebviewPanel(webviewPanel: vscode.WebviewPanel, state: any): Promise<void> {
        // This method is called when VS Code restarts and needs to restore the panel

        // Set up the webview again
        webviewPanel.webview.options = {
            enableScripts: true,
            localResourceRoots: [
                this._extensionUri,
                vscode.Uri.joinPath(this._extensionUri, 'dist')
            ]
        };

        // Restore HTML content (we'll need to get the run ID from state)
        const runId = state?.runId || 'unknown';
        webviewPanel.webview.html = this._getHtmlForWebview(webviewPanel.webview, runId);

        // Store panel reference
        this._panels.set(runId, webviewPanel);

        // Handle disposal
        webviewPanel.onDidDispose(() => {
            this._panels.delete(runId);
        });
    }

    public dispose(): void {
        this._panels.forEach(panel => panel.dispose());
        this._panels.clear();
    }
}
