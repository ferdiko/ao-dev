import * as child_process from 'child_process';
import * as vscode from 'vscode';
import WebSocket from 'ws';

export class PythonServerClient {
    private static instance: PythonServerClient;
    private client: WebSocket | undefined;
    private messageQueue: string[] = [];
    private messageCallbacks: ((msg: any) => void)[] = [];
    private connectionCallbacks: (() => void)[] = [];
    private serverHost: string;
    private serverPort: number;
    private reconnectTimer: NodeJS.Timeout | undefined;
    private _playbookUrl?: string;
    private _playbookApiKey?: string;

    private constructor() {
        const config = vscode.workspace.getConfiguration('ao');
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
        console.log('[AO] ensureConnected called, client exists:', !!this.client);
        if (!this.client || this.client.readyState === WebSocket.CLOSED || this.client.readyState === WebSocket.CLOSING) {
            this.connect();
        }
    }

    private connect() {
        console.log('[AO] connect() called');
        // Clean up existing client
        if (this.client) {
            this.client.removeAllListeners();
            try { this.client.close(); } catch { /* ignore */ }
        }

        const wsUrl = `ws://${this.serverHost}:${this.serverPort}/ws`;
        this.client = new WebSocket(wsUrl);

        this.client.on('open', () => {
            console.log('[AO] WebSocket connected');
            // No handshake needed — the server sends session_id on connect
            // Flush queued messages
            this.messageQueue.forEach(msg => this.client!.send(msg));
            this.messageQueue = [];
            // Notify connection listeners
            this.connectionCallbacks.forEach(callback => callback());
        });

        this.client.on('message', (data: WebSocket.Data) => {
            const text = data.toString();
            try {
                const msg = JSON.parse(text);
                this.messageCallbacks.forEach(callback => callback(msg));
            } catch {
                console.log('[AO] Failed to parse message:', text.slice(0, 100));
            }
        });

        this.client.on('close', () => {
            console.log('[AO] WebSocket closed');
            this.client = undefined;
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
            }
            this.reconnectTimer = setTimeout(() => this.ensureConnected(), 2000);
        });

        this.client.on('error', (err: Error) => {
            console.log('[AO] WebSocket error:', err.message);
            if (err.message.includes('ECONNREFUSED')) {
                console.log('[AO] Server not running, starting...');
                this.startServerIfNeeded();
            }
        });
    }

    public sendMessage(message: any) {
        const msgStr = JSON.stringify(message);
        if (this.client && this.client.readyState === WebSocket.OPEN) {
            try {
                this.client.send(msgStr);
            } catch {
                this.messageQueue.push(msgStr);
            }
        } else {
            this.messageQueue.push(msgStr);
            this.ensureConnected();
        }
    }

    public startServerIfNeeded() {
        console.log('[AO] startServerIfNeeded() called');
        const pythonPath = this.getPythonPath();
        console.log(`[AO] Starting server with: ${pythonPath} -m ao.cli.ao_server start`);

        const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
        const env: NodeJS.ProcessEnv = { ...process.env };
        if (workspaceRoot) {
            env.AO_WORKSPACE_ROOT = workspaceRoot;
        }

        const proc = child_process.spawn(pythonPath, ['-m', 'ao.cli.ao_server', 'start'], {
            detached: true,
            stdio: 'pipe',
            shell: false,
            env: env
        });
        proc.stdout?.on('data', (data) => console.log('[AO] server stdout:', data.toString()));
        proc.stderr?.on('data', (data) => console.log('[AO] server stderr:', data.toString()));
        proc.on('error', (err) => console.log('[AO] spawn error:', err));
        proc.on('exit', (code) => console.log('[AO] spawn exit code:', code));
        proc.unref();
    }

    private getPythonPath(): string {
        const aoHome = process.env.AO_HOME || require('path').join(require('os').homedir(), '.ao');
        const configPath = process.env.AO_CONFIG || require('path').join(aoHome, 'config.yaml');
        try {
            const fs = require('fs');
            if (fs.existsSync(configPath)) {
                const content = fs.readFileSync(configPath, 'utf8');
                const match = content.match(/python_executable:\s*(.+)/);
                if (match && match[1]) {
                    const pythonPath = match[1].trim();
                    console.log('[AO] Found python_executable in config:', pythonPath);
                    return pythonPath;
                }
            }
        } catch (err) {
            console.log('[AO] Could not read config:', err);
        }
        console.log('[AO] No python_executable in config, falling back to python3');
        return 'python3';
    }

    public stopServer() {
        this.sendMessage({ type: "shutdown" });
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
        this.messageQueue = [];
    }
}
