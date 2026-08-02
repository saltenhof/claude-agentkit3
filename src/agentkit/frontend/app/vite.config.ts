import react from '@vitejs/plugin-react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { defineConfig } from 'vite';

const repoRoot = resolve(import.meta.dirname, '../../../..');
const cert = readFileSync(resolve(repoRoot, 'var/devcert/cert.pem'));
const key = readFileSync(resolve(repoRoot, 'var/devcert/key.pem'));

// FK-10 §10.7.2 port registry / FK-15 §15: the SPA is the Strategen surface and
// talks EXCLUSIVELY to the UI-BFF (9701) — never to the Project-API (9702),
// which serves machine principals (hooks/edge/CLI). Keep in sync with
// CORE_UI_BFF_PORT in src/agentkit/backend/config/defaults.py.
const uiBffTarget = 'https://127.0.0.1:9701';

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
        target: uiBffTarget,
        changeOrigin: true,
        secure: false,
      },
      '/healthz': {
        target: uiBffTarget,
        changeOrigin: true,
        secure: false,
      },
    },
  },
});
