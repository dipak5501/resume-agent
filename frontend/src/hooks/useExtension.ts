import { useEffect, useState } from 'react'

export interface ExtensionStatus {
  installed: boolean
  backendOk: boolean
  /** Content script is present and its background worker reached GET /health. */
  active: boolean
}

function readStatus(): ExtensionStatus {
  const root = document.documentElement
  const installed = root.dataset.resumeAgent != null
  const backendOk = root.dataset.resumeAgentBackend === 'ok'
  return { installed, backendOk, active: installed && backendOk }
}

/** Installed when the extension's content script stamps the page. Active only
 *  after that script's background worker gets a healthy reply from the backend. */
export function useExtensionStatus(): ExtensionStatus {
  const [status, setStatus] = useState(readStatus)
  useEffect(() => {
    const sync = () => setStatus(readStatus())
    sync()
    window.addEventListener('resume-agent:present', sync)
    return () => window.removeEventListener('resume-agent:present', sync)
  }, [])
  return status
}

export function useExtensionInstalled(): boolean {
  return useExtensionStatus().installed
}
