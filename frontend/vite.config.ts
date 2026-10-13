/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    // Same-origin API in development, like the production ingress.
    proxy: { '/api': { target: process.env.VITE_DEV_API ?? 'http://localhost:8010', changeOrigin: true } },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/shared/lib/test-setup.ts'],
    css: false,
  },
})
