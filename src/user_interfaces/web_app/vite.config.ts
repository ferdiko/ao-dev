/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
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
