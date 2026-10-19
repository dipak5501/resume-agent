// Background service worker (T12). The ONLY actor that talks to our backend.
// Running in the extension origin with host_permissions, its fetches bypass the
// page's CORS — so ① (website/backend) and ③ (ATS) never talk directly.
import { BACKEND_URL } from '../shared/config'
import type { AnswerResult, JobSummary, Mapping, PdfPayload, Profile } from '../shared/types'

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  handle(msg)
    .then(sendResponse)
    .catch((e) => sendResponse({ error: String(e?.message ?? e) }))
  return true // async response
})

async function handle(msg: { type?: string; [k: string]: unknown }): Promise<unknown> {
  switch (msg?.type) {
    case 'HEALTH':
      return health()
    case 'LIST_JOBS':
      return api<JobSummary[]>('/jobs')
    case 'GET_PROFILE':
      return api<Profile>('/profile')
    case 'GET_PDF':
      return getPdf(msg.jobId as string)
    case 'MAP_FIELDS': // Phase 2 — send structure only, get canonical mappings back
      return api<{ mappings: Mapping[] }>('/autofill/map', {
        method: 'POST',
        body: JSON.stringify({ host: msg.host, fields: msg.fields }),
      })
    case 'CORRECT': // T19 learning loop — structure + corrected canonical only, NEVER a value
      return api('/autofill/correct', {
        method: 'POST',
        body: JSON.stringify({
          host: msg.host,
          fields: msg.fields,
          field_ref: msg.field_ref,
          corrected_canonical: msg.corrected_canonical,
        }),
      })
    case 'ANSWER': // T13 — question + job_id + host only; never other filled data or page HTML
      return api<AnswerResult>('/autofill/answer', {
        method: 'POST',
        body: JSON.stringify({ question: msg.question, job_id: msg.jobId, host: msg.host }),
      })
    case 'SAVE_ANSWER': // T13 — promote an edited AI draft into the reusable answer bank
      return api('/answers', {
        method: 'POST',
        body: JSON.stringify({ question: msg.question, answer: msg.answer, mode: 'adaptable' }),
      })
    case 'AUTO_APPLY_CLAIM':
      return api<{ job_id: string | null; apply_url: string | null }>('/auto-apply/claim', {
        method: 'POST',
        body: JSON.stringify({ page_url: msg.pageUrl }),
      })
    case 'AUTO_APPLY_FINISH':
      return api(`/jobs/${msg.jobId}/auto-apply/finish`, {
        method: 'POST',
        body: JSON.stringify({
          submitted: msg.submitted,
          unknown_required: msg.unknownRequired ?? [],
          blocked: msg.blocked ?? null,
        }),
      })
    default:
      throw new Error(`unknown message: ${msg?.type}`)
  }
}

async function health(): Promise<{ ok: boolean }> {
  const res = await fetch(`${BACKEND_URL}/health`)
  if (!res.ok) throw new Error(`health ${res.status}`)
  return { ok: true }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BACKEND_URL}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) throw new Error(`${path} → ${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

async function getPdf(jobId: string): Promise<PdfPayload> {
  const res = await fetch(`${BACKEND_URL}/jobs/${jobId}/pdf`)
  if (!res.ok) throw new Error(`PDF ${res.status}`)
  const buf = await res.arrayBuffer()
  return { base64: bytesToBase64(new Uint8Array(buf)), filename: 'resume.pdf' }
}

function bytesToBase64(bytes: Uint8Array): string {
  let bin = ''
  for (let i = 0; i < bytes.length; i += 0x8000) {
    bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  }
  return btoa(bin)
}
