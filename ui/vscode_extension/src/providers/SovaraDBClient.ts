/**
 * Direct HTTP+SSE client for SovaraDB.
 *
 * Handles prior CRUD via HTTP and real-time change notifications via SSE,
 * bypassing so-server entirely for prior operations.
 */

import * as http from 'http';
import * as https from 'https';
import { EventEmitter } from 'events';

export class SovaraDBClient extends EventEmitter {
    private static _instance: SovaraDBClient | null = null;

    private _baseUrl: string;
    private _sseRequest: http.ClientRequest | null = null;
    private _sseReconnectTimer: NodeJS.Timeout | null = null;
    private _disposed = false;

    private constructor(baseUrl: string) {
        super();
        this._baseUrl = baseUrl.replace(/\/$/, '');
    }

    static init(baseUrl: string): SovaraDBClient {
        if (SovaraDBClient._instance) {
            SovaraDBClient._instance.dispose();
        }
        SovaraDBClient._instance = new SovaraDBClient(baseUrl);
        SovaraDBClient._instance.connectEvents();
        return SovaraDBClient._instance;
    }

    static getInstance(): SovaraDBClient | null {
        return SovaraDBClient._instance;
    }

    // ============================================================
    // HTTP helpers
    // ============================================================

    private _httpModule(): typeof http | typeof https {
        return this._baseUrl.startsWith('https') ? https : http;
    }

    /** Make an HTTP request and return parsed JSON. */
    private _request(method: string, path: string, body?: any): Promise<any> {
        return new Promise((resolve, reject) => {
            const url = new URL(`${this._baseUrl}${path}`);
            const mod = this._httpModule();
            const headers: Record<string, string> = { 'Content-Type': 'application/json' };

            const payload = body !== undefined ? JSON.stringify(body) : undefined;
            if (payload) {
                headers['Content-Length'] = Buffer.byteLength(payload).toString();
            }

            const req = mod.request(url, { method, headers }, (res) => {
                const chunks: Buffer[] = [];
                res.on('data', (chunk: Buffer) => chunks.push(chunk));
                res.on('end', () => {
                    const raw = Buffer.concat(chunks).toString('utf-8');
                    if (!raw) { resolve({}); return; }
                    try { resolve(JSON.parse(raw)); }
                    catch { reject(new Error(`Invalid JSON: ${raw.slice(0, 200)}`)); }
                });
            });
            req.on('error', reject);
            req.setTimeout(120_000, () => { req.destroy(); reject(new Error('Request timeout')); });
            if (payload) { req.write(payload); }
            req.end();
        });
    }

    /**
     * Make an HTTP request expecting an SSE response (for mutations).
     * Reads the stream, extracts the `result` or `error` event, returns as Promise.
     */
    private _sseRequest_mutation(method: string, path: string, body?: any): Promise<any> {
        return new Promise((resolve, reject) => {
            const url = new URL(`${this._baseUrl}${path}`);
            const mod = this._httpModule();
            const headers: Record<string, string> = {
                'Content-Type': 'application/json',
                'Accept': 'text/event-stream',
            };

            const payload = body !== undefined ? JSON.stringify(body) : undefined;
            if (payload) {
                headers['Content-Length'] = Buffer.byteLength(payload).toString();
            }

            const req = mod.request(url, { method, headers }, (res) => {
                let buffer = '';
                let currentEvent = '';

                res.on('data', (chunk: Buffer) => {
                    buffer += chunk.toString('utf-8');
                    // Parse SSE frames
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || ''; // Keep incomplete line

                    for (const line of lines) {
                        if (line.startsWith('event: ')) {
                            currentEvent = line.slice(7).trim();
                        } else if (line.startsWith('data: ')) {
                            const dataStr = line.slice(6);
                            try {
                                const data = JSON.parse(dataStr);
                                if (currentEvent === 'result') {
                                    resolve(data);
                                } else if (currentEvent === 'error') {
                                    resolve({ error: data.error || 'Unknown error' });
                                }
                            } catch { /* ignore parse errors for non-terminal events */ }
                            currentEvent = '';
                        }
                    }
                });
                res.on('end', () => {
                    // If we never got a result/error event
                    resolve({ error: 'SSE stream ended unexpectedly' });
                });
            });
            req.on('error', reject);
            req.setTimeout(120_000, () => { req.destroy(); reject(new Error('Request timeout')); });
            if (payload) { req.write(payload); }
            req.end();
        });
    }

    // ============================================================
    // Prior CRUD
    // ============================================================

    async fetchFolder(path: string): Promise<any> {
        return this._request('POST', '/api/v1/priors/folders/ls', { path });
    }

    async getPrior(id: string): Promise<any> {
        return this._request('GET', `/api/v1/priors/${id}`);
    }

    async getPriorsList(): Promise<any> {
        return this._request('GET', '/api/v1/priors');
    }

    async createPrior(data: { name: string; summary: string; content: string; path?: string }, force: boolean): Promise<any> {
        const qs = force ? '?force=true' : '';
        return this._sseRequest_mutation('POST', `/api/v1/priors${qs}`, data);
    }

    async updatePrior(id: string, data: { name?: string; summary?: string; content?: string; path?: string }, force: boolean): Promise<any> {
        const qs = force ? '?force=true' : '';
        return this._sseRequest_mutation('PUT', `/api/v1/priors/${id}${qs}`, data);
    }

    async deletePrior(id: string): Promise<any> {
        return this._sseRequest_mutation('DELETE', `/api/v1/priors/${id}`);
    }

    // ============================================================
    // SSE subscription for real-time events
    // ============================================================

    connectEvents(): void {
        if (this._disposed) { return; }
        this._cleanupSse();

        const url = new URL(`${this._baseUrl}/api/v1/events`);
        const mod = this._httpModule();
        const headers: Record<string, string> = { 'Accept': 'text/event-stream' };

        const req = mod.request(url, { method: 'GET', headers }, (res) => {
            if (res.statusCode !== 200) {
                console.warn(`[SovaraDBClient] SSE connect failed: ${res.statusCode}`);
                this._scheduleReconnect();
                return;
            }

            let buffer = '';
            let currentEvent = '';

            res.on('data', (chunk: Buffer) => {
                buffer += chunk.toString('utf-8');
                const lines = buffer.split('\n');
                buffer = lines.pop() || '';

                for (const line of lines) {
                    if (line.startsWith('event: ')) {
                        currentEvent = line.slice(7).trim();
                    } else if (line.startsWith('data: ')) {
                        const dataStr = line.slice(6);
                        if (currentEvent) {
                            try {
                                const data = JSON.parse(dataStr);
                                this.emit('prior_event', { type: currentEvent, ...data });
                            } catch { /* ignore */ }
                        }
                        currentEvent = '';
                    }
                    // Ignore keepalive comments (lines starting with ':')
                }
            });

            res.on('end', () => {
                console.log('[SovaraDBClient] SSE connection ended');
                this._scheduleReconnect();
            });

            res.on('error', (err) => {
                console.warn('[SovaraDBClient] SSE stream error:', err.message);
                this._scheduleReconnect();
            });
        });

        req.on('error', (err) => {
            console.warn('[SovaraDBClient] SSE connect error:', err.message);
            this._scheduleReconnect();
        });

        req.end();
        this._sseRequest = req;
    }

    private _scheduleReconnect(): void {
        if (this._disposed) { return; }
        this._sseReconnectTimer = setTimeout(() => this.connectEvents(), 5000);
    }

    private _cleanupSse(): void {
        if (this._sseReconnectTimer) {
            clearTimeout(this._sseReconnectTimer);
            this._sseReconnectTimer = null;
        }
        if (this._sseRequest) {
            this._sseRequest.destroy();
            this._sseRequest = null;
        }
    }

    // ============================================================
    // Lifecycle
    // ============================================================

    dispose(): void {
        this._disposed = true;
        this._cleanupSse();
        this.removeAllListeners();
        if (SovaraDBClient._instance === this) {
            SovaraDBClient._instance = null;
        }
    }
}
