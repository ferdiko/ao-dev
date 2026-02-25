import * as net from 'net';
import * as child_process from 'child_process';
import * as vscode from 'vscode';

export class PythonServerClient {
    private static instance: PythonServerClient;
    private client: any = undefined;
    private messageQueue: string[] = [];
    private onMessageCallback?: (msg: any) => void;
    private messageCallbacks: ((msg: any) => void)[] = [];
    private connectionCallbacks: (() => void)[] = [];
    private serverHost: string;
    private serverPort: number;
    private serverUrl?: string;
    private useWebSocket = false;
    private reconnectTimer: NodeJS.Timeout | undefined;
    private _playbookUrl?: string;
    private _playbookApiKey?: string;

    private constructor() {
        // Read server configuration from VSCode settings
        const config = vscode.workspace.getConfiguration('ao');
        this.serverHost = config.get('pythonServerHost') || '127.0.0.1';
        this.serverPort = config.get('pythonServerPort') || 5959;
        this.serverUrl = config.get('pythonServerUrl');
        this.useWebSocket = !!(this.serverUrl && typeof this.serverUrl === 'string' && this.serverUrl.startsWith('ws'));

        // Don't auto-connect - let the extension control when to connect
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
        if (!this.client) {
            this.connect();
        }
    }

    private connect() {
        console.log('[AO] connect() called');
        // Clean up existing client before reconnecting
        if (this.client) {
            this.client.removeAllListeners();
            this.client.destroy();
        }

        // Create a new socket for each connection attempt
        this.client = new net.Socket();

        this.client.connect(5959, '127.0.0.1', () => {
            console.log('[AO] Connected successfully');
            const handshake = {
                type: "hello",
                role: "ui",
                script: "vscode-extension",
                workspace_root: vscode.workspace.workspaceFolders?.[0]?.uri.fsPath
            };

            this.client.write(JSON.stringify(handshake) + "\n");
            this.messageQueue.forEach(msg => this.client.write(msg));
            this.messageQueue = [];

            // Notify connection listeners (e.g., to request experiment list)
            this.connectionCallbacks.forEach(callback => callback());
        });

        let buffer = '';
        this.client.on('data', (data: Buffer) => {
            buffer += data.toString();
            let idx;
            while ((idx = buffer.indexOf('\n')) !== -1) {
                const line = buffer.slice(0, idx);
                buffer = buffer.slice(idx + 1);
                const msg = JSON.parse(line);
                // Call all registered callbacks
                this.messageCallbacks.forEach(callback => callback(msg));
            }
        });

        this.client.on('close', () => {
            console.log('[AO] Connection closed');
            this.client = undefined;  // Reset so ensureConnected() will reconnect
            // Clear any pending reconnect
            if (this.reconnectTimer) {
                clearTimeout(this.reconnectTimer);
            }
            // Use ensureConnected for reconnections to check auth first
            this.reconnectTimer = setTimeout(() => this.ensureConnected(), 2000);
        });

        this.client.on('error', (err: any) => {
            console.log('[AO] Connection error:', err.code, err.message);
            // Connection refused means server isn't running - try to start it
            if (err.code === 'ECONNREFUSED') {
                console.log('[AO] Server not running, starting...');
                this.startServerIfNeeded();
            }
            // Don't reconnect here - 'close' event fires after 'error' and handles reconnection
        });
    }

    public sendMessage(message: any) {
        const msgStr = JSON.stringify(message) + "\n";
        // WebSocket client (ws) has send() and numeric readyState
        if (this.client) {
            // WebSocket
            if (typeof this.client.send === 'function') {
                const isOpen = (typeof this.client.readyState === 'number' && this.client.readyState === 1); // 1 === OPEN
                if (isOpen) {
                    try { this.client.send(msgStr); } catch (e) { this.messageQueue.push(msgStr); }
                } else {
                    this.messageQueue.push(msgStr);
                }
                return;
            }

            // TCP socket (net.Socket)
            if (typeof this.client.write === 'function') {
                if (this.client.writable) {
                    try { this.client.write(msgStr); } catch (e) { this.messageQueue.push(msgStr); }
                } else {
                    this.messageQueue.push(msgStr);
                }
                return;
            }
        }

        // No connection - queue message and trigger reconnection
        console.log('[AO] No connection, queuing message and triggering reconnect');
        this.messageQueue.push(msgStr);
        this.ensureConnected();
    }

    public startServerIfNeeded() {
        console.log('[AO] startServerIfNeeded() called');
        const pythonPath = this.getPythonPath();
        console.log(`[AO] Starting server with: ${pythonPath} -m ao.cli.ao_server start`);

        // Pass workspace root to server via environment variable
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
        // Read python_executable from ~/.cache/ao/config.yaml
        const configPath = require('path').join(require('os').homedir(), '.cache', 'ao', 'config.yaml');
        try {
            const fs = require('fs');
            if (fs.existsSync(configPath)) {
                const content = fs.readFileSync(configPath, 'utf8');
                // Simple YAML parsing for python_executable field
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
        // Clear reconnect timeout
        if (this.reconnectTimer) {
            clearTimeout(this.reconnectTimer);
            this.reconnectTimer = undefined;
        }

        // Clean up socket
        if (this.client) {
            this.client.removeAllListeners();
            this.client.destroy();
        }

        // Clear callbacks
        this.messageCallbacks = [];
        this.connectionCallbacks = [];
        this.messageQueue = [];
    }
} 