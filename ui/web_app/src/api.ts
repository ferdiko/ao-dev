/**
 * Shared HTTP transport helpers for the Sovara frontend.
 *
 * Domain-specific API modules should import `get` / `post` from here instead of
 * adding their own backend startup / recovery logic.
 */

const BACKEND_START_TIMEOUT_MS = 10_000;
const BACKEND_HEALTH_POLL_MS = 250;
let backendStartupPromise: Promise<void> | null = null;

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    const resp = await fetch("/_sovara/health");
    return resp.ok;
  } catch {
    return false;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

async function parseJsonResponse<T>(resp: Response, method: string, path: string): Promise<T> {
  if (!resp.ok) {
    const data = await resp.json().catch(() => null);
    throw new Error(data?.detail ?? data?.error ?? `${method} ${path} failed: ${resp.status}`);
  }
  return resp.json();
}

async function ensureBackendRunning(skipInitialHealthCheck = false): Promise<void> {
  if (!skipInitialHealthCheck && await isBackendHealthy()) {
    return;
  }

  if (!backendStartupPromise) {
    backendStartupPromise = (async () => {
      const startResp = await fetch("/_sovara/start-server", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      if (!startResp.ok) {
        throw new Error(`POST /_sovara/start-server failed: ${startResp.status}`);
      }

      const deadline = Date.now() + BACKEND_START_TIMEOUT_MS;
      while (Date.now() < deadline) {
        if (await isBackendHealthy()) {
          return;
        }
        await sleep(BACKEND_HEALTH_POLL_MS);
      }

      throw new Error("Timed out waiting for the Sovara backend to start");
    })().finally(() => {
      backendStartupPromise = null;
    });
  }

  await backendStartupPromise;
}

async function maybeRecoverBackend(status?: number): Promise<boolean> {
  if (status !== undefined && status < 500) {
    return false;
  }
  if (await isBackendHealthy()) {
    return false;
  }
  await ensureBackendRunning(true);
  return true;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";

  try {
    const resp = await fetch(path, init);
    if (!resp.ok && await maybeRecoverBackend(resp.status)) {
      return parseJsonResponse<T>(await fetch(path, init), method, path);
    }
    return parseJsonResponse<T>(resp, method, path);
  } catch (error) {
    if (isAbortError(error)) {
      throw error;
    }
    if (await maybeRecoverBackend()) {
      return parseJsonResponse<T>(await fetch(path, init), method, path);
    }
    throw error;
  }
}

export async function get<T>(path: string, init?: RequestInit): Promise<T> {
  return requestJson<T>(path, init);
}

export async function post<T>(path: string, body: unknown, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Content-Type", "application/json");
  return requestJson<T>(path, {
    ...init,
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
}
