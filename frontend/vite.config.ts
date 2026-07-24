/// <reference types="vitest/config" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Keep the browser on the Vite origin while forwarding API calls to the
// source-mode FastAPI process during local development. Without this, Vite's
// SPA fallback returns index.html for /api/*, which the client correctly
// rejects as a non-JSON response.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:18088',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: '../dist',
    emptyOutDir: true,
    sourcemap: false,
    minify: 'oxc',
  },
  test: {
    // Playwright specs live under e2e/; keep them out of vitest discovery.
    exclude: [
      '**/node_modules/**',
      '**/dist/**',
      '**/e2e/**',
      '**/playwright-report/**',
    ],
  },
});
