/// <reference types="vitest/config" />
import { spawn } from 'node:child_process'
import process from 'node:process'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

const BACKEND_START_TIMEOUT_MS = 10_000
const BACKEND_HEALTH_POLL_MS = 250

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms)
  })
}

async function isBackendHealthy(): Promise<boolean> {
  try {
    const resp = await fetch('http://127.0.0.1:5959/health')
    return resp.ok
  } catch {
    return false
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'sovara-dev-server-control',
      configureServer(server) {
        let backendStartupPromise: Promise<void> | null = null

        async function ensureBackendRunning(): Promise<void> {
          if (await isBackendHealthy()) {
            return
          }

          if (!backendStartupPromise) {
            backendStartupPromise = (async () => {
              const workspaceRoot = path.resolve(__dirname, '..', '..')
              const child = spawn(
                'python3',
                ['-m', 'sovara.cli.so_server', 'start'],
                {
                  cwd: workspaceRoot,
                  detached: true,
                  stdio: 'ignore',
                  env: {
                    ...process.env,
                    SOVARA_WORKSPACE_ROOT: workspaceRoot,
                  },
                },
              )
              child.unref()

              const deadline = Date.now() + BACKEND_START_TIMEOUT_MS
              while (Date.now() < deadline) {
                if (await isBackendHealthy()) {
                  return
                }
                await sleep(BACKEND_HEALTH_POLL_MS)
              }

              throw new Error('Timed out waiting for the Sovara backend to start')
            })().finally(() => {
              backendStartupPromise = null
            })
          }

          await backendStartupPromise
        }

        server.middlewares.use('/_sovara/health', (_req, res) => {
          isBackendHealthy()
            .then((ok) => {
              res.statusCode = ok ? 200 : 503
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ ok }))
            })
        })

        server.middlewares.use('/_sovara/start-server', (req, res) => {
          if (req.method !== 'POST') {
            res.statusCode = 405
            res.end()
            return
          }

          ensureBackendRunning()
            .then(() => {
              res.statusCode = 202
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ ok: true }))
            })
            .catch((error) => {
              res.statusCode = 500
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({
                ok: false,
                error: error instanceof Error ? error.message : String(error),
              }))
            })
        })
      },
    },
  ],
  resolve: {
    alias: {
      '@sovara/shared-components': path.resolve(__dirname, '../shared_components'),
      react: path.resolve(__dirname, 'node_modules/react'),
      'react-dom': path.resolve(__dirname, 'node_modules/react-dom'),
      'react/jsx-runtime': path.resolve(__dirname, 'node_modules/react/jsx-runtime.js'),
      'react/jsx-dev-runtime': path.resolve(__dirname, 'node_modules/react/jsx-dev-runtime.js'),
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: './src/setupTests.ts',
  },
  server: {
    proxy: {
      '/ui': {
        target: 'http://127.0.0.1:5959',
        changeOrigin: true,
      },
      '/ws': {
        target: 'ws://127.0.0.1:5959',
        ws: true,
      },
    },
  },
})
