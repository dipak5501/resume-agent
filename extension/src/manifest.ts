import { defineManifest } from '@crxjs/vite-plugin'

// MV3, least privilege (T12): activeTab/scripting/storage only, and
// host_permissions scoped to the supported ATS domains + our dev backend —
// never <all_urls>. The ATS host list is a semi-open registry (grows like T10).
const ATS_HOSTS = [
  'https://*.greenhouse.io/*',
  'https://*.lever.co/*',
  'https://*.ashbyhq.com/*',
  'https://*.myworkdayjobs.com/*',
]
const BACKEND = ['http://127.0.0.1:8000/*', 'http://localhost:8000/*']
// The Resume Agent web app itself — a detect-only content script flags the app
// that the extension is installed (T14 onboarding). Dev origins for now; add the
// deployed origin at T8. ponytail: two localhost forms cover the Vite dev server.
const WEBAPP_HOSTS = ['http://localhost:5173/*', 'http://127.0.0.1:5173/*']

export default defineManifest({
  manifest_version: 3,
  name: 'Resume Agent — Assisted Autofill',
  version: '0.1.0',
  description:
    'Fills an ATS form from your profile and tailored résumé. You submit, unless you turned on Auto-apply for one run.',
  action: { default_popup: 'index.html', default_title: 'Resume Agent' },
  permissions: ['activeTab', 'scripting', 'storage'],
  host_permissions: [...ATS_HOSTS, ...BACKEND],
  // NOTE: distinct basename (not another index.ts) — CRXJS/Rollup key emitted
  // chunks by basename, so a second `index.ts` entry collides with the content
  // script and one silently overwrites the other's bundle. Keep entries uniquely named.
  background: { service_worker: 'src/background/service-worker.ts', type: 'module' },
  content_scripts: [
    {
      matches: ATS_HOSTS,
      js: ['src/content/index.ts'],
      run_at: 'document_idle',
    },
    {
      // detect-only, on the web app: set the "installed" flag before the app mounts
      matches: WEBAPP_HOSTS,
      js: ['src/content/detect-webapp.ts'],
      run_at: 'document_start',
    },
  ],
})
