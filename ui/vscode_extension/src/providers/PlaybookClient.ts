/**
 * Direct HTTP+SSE client for ao-playbook.
 *
 * Handles lesson CRUD via HTTP and real-time change notifications via SSE,
 * bypassing so-server entirely for lesson operations.
 */

import * as http from 'http';
import * as https from 'https';
import { EventEmitter } from 'events';

export class PlaybookClient extends EventEmitter {
    private static _instance: PlaybookClient | null = null;

    private _baseUrl: string;
    private _apiKey: string;
    private _sseRequest: http.ClientRequest | null = null;
    private _sseReconnectTimer: NodeJS.Timeout | null = null;
    private _disposed = false;

    private constructor(baseUrl: string, apiKey: string) {
        super();
        this._baseUrl = baseUrl.replace(/\/$/, '');
        this._apiKey = apiKey;
    }

    static init(baseUrl: string, apiKey: string): PlaybookClient {
        if (PlaybookClient._instance) {
            PlaybookClient._instance.dispose();
        }
        PlaybookClient._instance = new PlaybookClient(baseUrl, apiKey);
        PlaybookClient._instance.connectEvents();
        return PlaybookClient._instance;
    }

    static getInstance(): PlaybookClient | null {
        return PlaybookClient._instance;
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
            if (this._apiKey) {
                headers['X-API-Key'] = this._apiKey;
            }

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
            if (this._apiKey) {
                headers['X-API-Key'] = this._apiKey;
            }

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
    // Lesson CRUD
    // ============================================================

    async fetchFolder(path: string): Promise<any> {
        return this._request('POST', '/api/v1/lessons/folders/ls', { path });
    }

    async getLesson(id: string): Promise<any> {
        return this._request('GET', `/api/v1/lessons/${id}`);
    }

    async getLessonsList(): Promise<any> {
        return this._request('GET', '/api/v1/lessons');
    }

    async createLesson(data: { name: string; summary: string; content: string; path?: string }, force: boolean): Promise<any> {
        const qs = force ? '?force=true' : '';
        return this._sseRequest_mutation('POST', `/api/v1/lessons${qs}`, data);
    }

    async updateLesson(id: string, data: { name?: string; summary?: string; content?: string; path?: string }, force: boolean): Promise<any> {
        const qs = force ? '?force=true' : '';
        return this._sseRequest_mutation('PUT', `/api/v1/lessons/${id}${qs}`, data);
    }

    async deleteLesson(id: string): Promise<any> {
        return this._sseRequest_mutation('DELETE', `/api/v1/lessons/${id}`);
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
        if (this._apiKey) {
            headers['X-API-Key'] = this._apiKey;
        }

        const req = mod.request(url, { method: 'GET', headers }, (res) => {
            if (res.statusCode !== 200) {
                console.warn(`[PlaybookClient] SSE connect failed: ${res.statusCode}`);
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
                                this.emit('lesson_event', { type: currentEvent, ...data });
                            } catch { /* ignore */ }
                        }
                        currentEvent = '';
                    }
                    // Ignore keepalive comments (lines starting with ':')
                }
            });

            res.on('end', () => {
                console.log('[PlaybookClient] SSE connection ended');
                this._scheduleReconnect();
            });

            res.on('error', (err) => {
                console.warn('[PlaybookClient] SSE stream error:', err.message);
                this._scheduleReconnect();
            });
        });

        req.on('error', (err) => {
            console.warn('[PlaybookClient] SSE connect error:', err.message);
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
        if (PlaybookClient._instance === this) {
            PlaybookClient._instance = null;
        }
    }
}
