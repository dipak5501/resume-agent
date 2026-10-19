// Runs on the Resume Agent web app. Tells the page the extension is installed,
// then asks the background worker whether the backend answered GET /health.
// The page cannot install this extension; it only reads the result.
const version = chrome.runtime.getManifest().version
const root = document.documentElement
root.dataset.resumeAgent = version
root.dataset.resumeAgentBackend = 'checking'

function publish(backend: boolean) {
  root.dataset.resumeAgentBackend = backend ? 'ok' : 'down'
  window.dispatchEvent(new CustomEvent('resume-agent:present', { detail: { version, backend } }))
}

chrome.runtime.sendMessage({ type: 'HEALTH' }, (resp) => {
  if (chrome.runtime.lastError) {
    publish(false)
    return
  }
  publish(Boolean(resp && (resp as { ok?: boolean }).ok))
})
