// One armed run, and only when Auto-apply is on. The ordinary Fill path never
// calls this. Unknown required fields, a CAPTCHA, a login wall, a paywall, or
// a bot check stop the submit. Nothing here evades detection or reads secrets.

export type BlockKind = 'captcha' | 'login' | 'paywall' | 'bot' | 'unreliable'

export interface GateInput {
  enabled: boolean
  applyUrl: string | null
  resumeReady: boolean
  unknownRequired: string[]
  blocked: BlockKind | null
}

export type GateResult = { ok: true; reason: string } | { ok: false; reason: string }

export function detectBlock(doc: Document): BlockKind | null {
  if (doc.querySelector('iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha, [data-sitekey]')) {
    return 'captcha'
  }
  if (doc.querySelector('input[type="password"]')) return 'login'
  const text = (doc.body?.innerText || '').slice(0, 4000).toLowerCase()
  if (/\b(subscribe to apply|payment required|paywall)\b/.test(text)) return 'paywall'
  if (/\b(verify you are human|unusual traffic|access denied)\b/.test(text)) return 'bot'
  return null
}

export function unknownRequired(
  plan: { field_ref: number; label: string; action: string; canonical?: string }[],
  fields: { field_ref: number; required: boolean; label: string }[],
): string[] {
  const byRef = new Map(plan.map((item) => [item.field_ref, item]))
  const labels: string[] = []
  for (const field of fields) {
    if (!field.required) continue
    const item = byRef.get(field.field_ref)
    if (!item || item.canonical === 'unknown' || item.action === 'flag' || item.action === 'blank' || item.action === 'answer') {
      labels.push(item?.label || field.label || 'required field')
    }
  }
  return labels
}

export function canAutoSubmit(input: GateInput): GateResult {
  if (!input.enabled) return { ok: false, reason: 'Auto-apply is off.' }
  if (!input.applyUrl) return { ok: false, reason: 'This run has no apply link.' }
  if (!input.resumeReady) return { ok: false, reason: 'The résumé is not finished.' }
  if (input.blocked === 'captcha') return { ok: false, reason: 'Left unsubmitted. This page has a CAPTCHA.' }
  if (input.blocked === 'login') return { ok: false, reason: 'Left unsubmitted. Sign in yourself first.' }
  if (input.blocked === 'paywall') return { ok: false, reason: 'Left unsubmitted. This page is behind a paywall.' }
  if (input.blocked === 'bot') return { ok: false, reason: 'Left unsubmitted. The site asked for a human check.' }
  if (input.blocked) return { ok: false, reason: 'Left unsubmitted. This form could not be filled reliably.' }
  if (input.unknownRequired.length) {
    return { ok: false, reason: 'A required field is unknown. Fill it yourself — nothing was submitted.' }
  }
  return { ok: true, reason: 'Filled from your profile and résumé.' }
}

/** Submit only after the gate passes. A failed check never touches the form. */
export function submitIfAllowed(form: HTMLFormElement, input: GateInput, onAccepted: () => void): GateResult {
  const gate = canAutoSubmit(input)
  if (!gate.ok) return gate
  const accept = () => onAccepted()
  form.addEventListener('submit', accept, { once: true })
  try {
    form.requestSubmit()
  } catch {
    form.removeEventListener('submit', accept)
    return { ok: false, reason: 'Left unsubmitted. The form could not be submitted.' }
  }
  return gate
}

export interface AutoApplyDeps {
  doc: Document
  href: string
  fill: (jobId: string) => Promise<{ unknownRequired?: string[]; error?: string }>
  claim: (pageUrl: string) => Promise<{ job_id?: string | null; apply_url?: string | null } | null>
  finish: (jobId: string, body: { submitted: boolean; unknown_required: string[]; blocked: string | null }) => Promise<unknown>
  profile: () => Promise<{ auto_apply?: boolean | null }>
  say?: (text: string) => void
}

function banner(doc: Document, text: string) {
  const el = doc.createElement('div')
  el.textContent = text
  el.setAttribute('role', 'status')
  el.style.cssText = 'position:fixed;bottom:16px;left:16px;z-index:2147483647;max-width:340px;background:#1c1915;color:#f4efe6;padding:12px 14px;font:13px/1.4 ui-monospace,monospace;border:1px solid #f3b41f;'
  doc.documentElement.appendChild(el)
}

function applicationForm(doc: Document): HTMLFormElement | null {
  return [...doc.forms].find((form) => !form.querySelector('input[type="password"]')) ?? null
}

export async function runAutoApply(deps: AutoApplyDeps): Promise<'submitted' | 'stopped' | 'idle'> {
  let claimed: { job_id?: string | null; apply_url?: string | null } | null = null
  try {
    claimed = await deps.claim(deps.href)
  } catch {
    return 'idle'
  }
  if (!claimed?.job_id || !claimed.apply_url) return 'idle'
  const say = deps.say ?? ((text: string) => banner(deps.doc, text))
  const jobId = claimed.job_id
  const stop = async (unknown: string[], blocked: string | null, text: string) => {
    await deps.finish(jobId, { submitted: false, unknown_required: unknown, blocked }).catch(() => {})
    say(text)
    return 'stopped' as const
  }
  let filled: { unknownRequired?: string[]; error?: string }
  try {
    filled = await deps.fill(jobId)
  } catch {
    return stop([], 'unreliable', 'Left unsubmitted. The form could not be filled.')
  }
  if (filled.error) return stop([], 'unreliable', filled.error)
  const unknown = filled.unknownRequired ?? []
  const blocked = detectBlock(deps.doc)
  let enabled = false
  try {
    enabled = Boolean((await deps.profile()).auto_apply)
  } catch {
    enabled = false
  }
  const form = applicationForm(deps.doc)
  if (!form) return stop(unknown, blocked ?? 'unreliable', 'Left unsubmitted. No application form to submit.')
  let accepted = false
  const decision = submitIfAllowed(form, {
    enabled,
    applyUrl: claimed.apply_url,
    resumeReady: true,
    unknownRequired: unknown,
    blocked,
  }, () => { accepted = true })
  if (!decision.ok) return stop(unknown, blocked, decision.reason)
  if (!accepted) return stop([], 'unreliable', 'Left unsubmitted. The form did not accept the submit.')
  try {
    await deps.finish(jobId, { submitted: true, unknown_required: [], blocked: null })
  } catch {
    say('The form was submitted, but it was not logged. Check Set up & track.')
    return 'stopped'
  }
  say('Submitted this one application. It is logged under Set up & track.')
  return 'submitted'
}

let started = false

export function startAutoApply(deps: AutoApplyDeps): void {
  if (started) return
  started = true
  void runAutoApply(deps)
}
