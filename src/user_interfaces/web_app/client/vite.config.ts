import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import fs from 'fs'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react({
    include: /\.(tsx|ts|jsx|js)$/,
  })],
  resolve: {
    alias: {
      // Check if we're in Docker (src/shared_components exists) or local (../../shared_components)
      '../../../shared_components': fs.existsSync(path.resolve(__dirname, 'src/shared_components'))
        ? path.resolve(__dirname, 'src/shared_components')
        : path.resolve(__dirname, '../../shared_components'),
    }
  },
  server: {
    port: 3000,
    fs: {
      // Allow serving files from the shared_components directory
      allow: ['..']
    },
    proxy: {
      '/ui': 'http://127.0.0.1:4000',
      '/health': 'http://127.0.0.1:4000',
      '/ws': { target: 'ws://127.0.0.1:4000', ws: true },
    }
  }
})
