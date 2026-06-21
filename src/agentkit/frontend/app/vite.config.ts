import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const repoRoot = resolve(import.meta.dirname, '../../../..');
const cert = readFileSync(resolve(repoRoot, 'var/devcert/cert.pem'));
const key = readFileSync(resolve(repoRoot, 'var/devcert/key.pem'));

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: false,
    https: {
      cert,
      key,
    },
    proxy: {
      '/v1': {
        target: 'https://127.0.0.1:9080',
        changeOrigin: true,
        secure: false,
      },
      '/healthz': {
        target: 'https://127.0.0.1:9080',
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
