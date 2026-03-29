/// <reference types="vitest/config" />
import { spawn } from 'node:child_process'
import process from 'node:process'
import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    {
      name: 'sovara-dev-server-control',
      configureServer(server) {
        server.middlewares.use('/_sovara/health', (_req, res) => {
          fetch('http://127.0.0.1:5959/health')
            .then((resp) => {
              res.statusCode = resp.ok ? 200 : 503
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ ok: resp.ok }))
            })
            .catch(() => {
              res.statusCode = 503
              res.setHeader('Content-Type', 'application/json')
              res.end(JSON.stringify({ ok: false }))
            })
        })

        server.middlewares.use('/_sovara/start-server', (req, res) => {
          if (req.method !== 'POST') {
            res.statusCode = 405
            res.end()
            return
          }

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
          res.statusCode = 202
          res.setHeader('Content-Type', 'application/json')
          res.end(JSON.stringify({ ok: true }))
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
