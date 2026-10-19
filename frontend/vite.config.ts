import path from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const BACKEND = 'http://localhost:8000'

// For paths that are both a backend endpoint and an SPA route: proxy the fetch,
// but let a top-level navigation fall through to index.html so React Router owns
// the URL (reload/bookmark work). fetch() sends Accept: */* — only a browser
// document nav carries text/html.
const SPA_SAFE = {
  target: BACKEND,
  bypass(req: { headers: Record<string, string | string[] | undefined> }) {
    const accept = req.headers.accept
    if (typeof accept === 'string' && accept.includes('text/html')) return '/index.html'
  },
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, './src') },
  },
  server: {
    // dev proxy → FastAPI backend, so no CORS needed
    proxy: {
      '/health': BACKEND,
      '/jobs': BACKEND,
      '/applications': BACKEND,
      '/jd': BACKEND,
      '/resumes': BACKEND,
      // /profile, /answers, and /board are ALSO client-side routes. A full-page
      // load of one must serve the SPA, not the API JSON — so proxy them only
      // for XHR/fetch (Accept: */*), never for a browser navigation (Accept:
      // text/html). The other paths never clash with a route.
      '/profile': SPA_SAFE,
      '/answers': SPA_SAFE,
      '/board': SPA_SAFE,
    },
  },
})
