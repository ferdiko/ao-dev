import * as child_process from 'child_process';
import * as vscode from 'vscode';
import WebSocket from 'ws';

export class PythonServerClient {
    private static instance: PythonServerClient;
    private client: WebSocket | undefined;
    private messageCallbacks: ((msg: any) => void)[] = [];
    private connectionCallbacks: (() => void)[] = [];
    private serverHost: string;
    private serverPort: number;
    private reconnectTimer: NodeJS.Timeout | undefined;
    private _playbookUrl?: string;
    private _playbookApiKey?: string;

    private constructor() {
        const config = vscode.workspace.getConfiguration('sovara');
        this.serverHost = config.get('pythonServerHost') || '127.0.0.1';
        this.serverPort = config.get('pythonServerPort') || 5959;
    }

    public static getInstance(): PythonServerClient {
        return PythonServerClient.instance ??= new PythonServerClient();
    }

    public setPlaybookUrl(url: string | undefined) {
        this._playbookUrl = url;
    }

    public getPlaybookUrl(): string | undefined {
        return this._playbookUrl;
    }

    public setPlaybookApiKey(key: string | undefined) {
        this._playbookApiKey = key;
    }

    public getPlaybookApiKey(): string | undefined {
        return this._playbookApiKey;
    }

    public async ensureConnected() {
        console.log('[Sovara] ensureConnected called, client exists:', !!this.client);
        if (!this.client || this.client.readyState === WebSocket.CLOSED || this.client.readyState === WebSocket.CLOSING) {
            this.connect();
        }
    }

    private get baseUrl(): string {
        return `http://${this.serverHost}:${this.serverPort}`;
    }

    /** HTTP GET to the sovara server. Returns parsed JSON. */
    public async httpGet(path: string): Promise<any> {
        const url = `${this.baseUrl}${path}`;
        const resp = await fetch(url);
        return resp.json();
    }

    /** HTTP POST to the sovara server. Returns parsed JSON. */
    public async httpPost(path: string, body: any = {}): Promise<any> {
        const url = `${this.baseUrl}${path}`;
        const resp = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        return resp.json();
    }

    private connect() {
        console.log('[Sovara] connect() called');
        // Clean up existing client
        if (this.client) {
            this.client.removeAllListeners();
            try { this.client.close(); } catch { /* ignore */ }
        }

        const wsUrl = `ws://${this.serverHost}:${this.serverPort}/ws`;
        this.client = new WebSocket(wsUrl);

        this.client.on('open', () => {
            console.log('[Sovara] WebSocket connected');
            // Notify connection listeners
            this.connectionCallbacks.forEach(callback => callback());
        });

        this.client.on('message', (data: WebSocket.Data) => {
            const text = data.toString();
            try {
                const msg = JSON.parse(text);
                this.messageCallbacks.forEach(callback => callback(msg));
            } catch {
                console.log('[Sovara] Failed to parse message:', text.slice(0, 100));
            }
        });

        this.client.on('close', () => {
            console.log('[Sovara] WebSocket closed');
            this.client = undefined;
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
            }
            this.reconnectTimer = setTimeout(() => this.ensureConnected(), 2000);
        });

        this.client.on('error', (err: Error) => {
            console.log('[Sovara] WebSocket error:', err.message);
            if (err.message.includes('ECONNREFUSED')) {
                console.log('[Sovara] Server not running, starting...');
                this.startServerIfNeeded();
            }
        });
    }

    public startServerIfNeeded() {
        console.log('[Sovara] startServerIfNeeded() called');
        const pythonPath = this.getPythonPath();
        console.log(`[Sovara] Starting server with: ${pythonPath} -m sovara.cli.so_server start`);

        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const env: NodeJS.ProcessEnv = { ...process.env };
        if (workspaceRoot) {
            env.SOVARA_WORKSPACE_ROOT = workspaceRoot;
        }

        const proc = child_process.spawn(pythonPath, ['-m', 'sovara.cli.so_server', 'start'], {
            detached: true,
            stdio: 'pipe',
            shell: false,
            env: env
        });
        proc.stdout?.on('data', (data) => console.log('[Sovara] server stdout:', data.toString()));
        proc.stderr?.on('data', (data) => console.log('[Sovara] server stderr:', data.toString()));
        proc.on('error', (err) => console.log('[Sovara] spawn error:', err));
        proc.on('exit', (code) => console.log('[Sovara] spawn exit code:', code));
        proc.unref();
    }

    private getPythonPath(): string {
        const aoHome = process.env.SOVARA_HOME || require('path').join(require('os').homedir(), '.sovara');
        const configPath = process.env.SOVARA_CONFIG || require('path').join(aoHome, 'config.yaml');
        try {
            const fs = require('fs');
            if (fs.existsSync(configPath)) {
                const content = fs.readFileSync(configPath, 'utf8');
                const match = content.match(/python_executable:\s*(.+)/);
                if (match && match[1]) {
                    const pythonPath = match[1].trim();
                    console.log('[Sovara] Found python_executable in config:', pythonPath);
                    return pythonPath;
                }
            }
        } catch (err) {
            console.log('[Sovara] Could not read config:', err);
        }
        console.log('[Sovara] No python_executable in config, falling back to python3');
        return 'python3';
    }

    public stopServer() {
        this.httpPost('/ui/shutdown').catch(() => {});
    }

    public onMessage(cb: (msg: any) => void) {
        this.messageCallbacks.push(cb);
    }

    public onConnection(cb: () => void) {
        this.connectionCallbacks.push(cb);
    }

    public removeMessageListener(cb: (msg: any) => void) {
        const index = this.messageCallbacks.indexOf(cb);
        if (index > -1) {
            this.messageCallbacks.splice(index, 1);
        }
    }

    public dispose() {
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = undefined;
        }
        if (this.client) {
            this.client.removeAllListeners();
            try { this.client.close(); } catch { /* ignore */ }
        }
        this.messageCallbacks = [];
        this.connectionCallbacks = [];
    }
}
