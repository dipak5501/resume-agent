import { crx } from '@crxjs/vite-plugin'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

import manifest from './src/manifest'

export default defineConfig({
  plugins: [react(), crx({ manifest })],
  // CRXJS uses a websocket for content-script HMR; harmless in build.
  server: { port: 5174, strictPort: true, hmr: { port: 5174 } },
})
