// Content script (T12). Runs in the ATS page, in the user's own session. It
// detects the form, fills factual fields, and attaches the tailored résumé.
// Fill itself never submits. A separate auto-apply path submits one armed run
// only after the user turned the switch on and every required field is known.
import { FILL_THRESHOLD } from '../shared/config'
import { YOURS } from '../shared/mark-kind'
import { sendToBackground } from '../shared/messaging'
import type { AnswerResult, FillResult, Mapping, PdfPayload, PlanItem, Profile } from '../shared/types'
import { acceptsFreeText, alreadyFilled, anyChecked, applyPlan, fillComboboxes, fitMaxLength, isCombobox, selectRadio, reapplyValue, setNativeValue } from './apply'
import { startAutoApply, unknownRequired } from './auto-apply'
import { decideChoice } from './choice-answer'
import { detectRadioGroups } from './choices'
import type { DetectedField } from './detector'
import { detectFields, fieldKeys } from './detector'
import { mapAll } from './mapper'
import { planFill, reverseCanonical } from './plan'
import { userTouched, watchTakeover } from './takeover'
import { focusField, renderProofMarks } from './proofmarks'

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === 'PING') {
    sendResponse({ ok: true })
    return
  }
  // DETECT (T15): lets the popup show the "not on an application page" state
  // proactively — a pure count, no values leave the page.
  if (msg?.type === 'DETECT') {
    const n = detectFields(document).length
    sendResponse({ formPresent: n > 0, fieldCount: n })
    return
  }
  // FOCUS_FIELD (T15): jump-to-field from the popup's review list.
  if (msg?.type === 'FOCUS_FIELD') {
    focusField(msg.field_ref as number)
    sendResponse({ ok: true })
    return
  }
  if (msg?.type === 'FILL') {
    const jobId = msg.jobId as string | null
    fill(jobId)
      .then((res) => {
        if (!res.error) watchSteps(jobId) // T19: keep re-filling as the wizard advances
        sendResponse(res)
      })
      .catch((e) => sendResponse(empty(String(e?.message ?? e))))
    return true // keep the message channel open for the async response
  }
})

async function fill(jobId: string | null): Promise<FillResult> {
  // From here on the user outranks us: a real keystroke, click, wheel or touch
  // stands the remaining fill down. A Greenhouse pass can run for a minute
  // (16 comboboxes x up to 4s, then one backend call per free-text field), and
  // the user starts correcting long before it ends.
  watchTakeover()
  const fields = detectFields(document)
  if (fields.length === 0) return empty('No application form detected on this page.')
  // Before any dropdown pick hides its input, so a pick the user later clears
  // doesn't come back looking like a new step.
  for (const k of fieldKeys(fields)) seenFields.add(k)

  const descriptors = fields.map((f) => f.descriptor)
  const profile = await sendToBackground<Profile>({ type: 'GET_PROFILE' })

  // Fast lane: deterministic mapping resolves the stable ~80% in-browser, free.
  const mappings = new Map(mapAll(descriptors).map((m) => [m.field_ref, m]))
  // LLM lane: ask the backend to resolve only what we couldn't — sending field
  // STRUCTURE ONLY (no values, no page HTML). Failures leave them unknown.
  const unresolved = descriptors.filter((d) => mappings.get(d.field_ref)?.canonical === 'unknown')
  if (unresolved.length) {
    try {
      const { mappings: resolved } = await sendToBackground<{ mappings: Mapping[] }>({
        type: 'MAP_FIELDS',
        host: location.host,
        fields: unresolved,
      })
      for (const m of resolved) mappings.set(m.field_ref, m)
    } catch {
      // backend unreachable → those fields stay unknown; planFill leaves them for the user
    }
  }

  // T19 learning loop: before we fill anything, learn from the user's OWN prior
  // fills — a field we couldn't map that already holds a profile value reveals
  // its canonical. Sends the CATEGORY only; the value never leaves the page.
  captureMappingCorrections(fields, mappings, profile)

  const resume = jobId ? await getResume(jobId) : null

  const plan = planFill(descriptors, mappings, profile, resume != null)
  applyPlan(fields, plan, resume)
  await fillComboboxes(fields, plan) // T19: ARIA comboboxes (Workday) — async open→type→pick
  await answerFreeText(fields, plan, jobId)

  // T17: radio-group screening questions (work-auth, EEO, legal attestations) —
  // pre-select from the user's profile / honest defaults, always flagged for review.
  const choice = fillChoices(fields.length, profile)

  const allFields = [...fields, ...choice.fields]
  const allPlan = [...plan, ...choice.plan]
  renderProofMarks(allFields, allPlan) // T15: mark the page like a proofread manuscript
  reassertFills(allFields, allPlan) // Ashby et al. re-render on résumé parse — re-apply after it settles
  return {
    ...group(allPlan),
    unknownRequired: unknownRequired(
      allPlan,
      allFields.map((f) => ({
        field_ref: f.descriptor.field_ref,
        required: f.descriptor.required,
        label: f.descriptor.label,
      })),
    ),
  }
}

/** The live element for a field descriptor — re-queried by id/name so a form
 *  that swapped the DOM node out (an ATS re-render) is still reachable. */
function liveElement(f: DetectedField): HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null {
  const d = f.descriptor
  const byId = d.id && document.getElementById(d.id)
  if (byId) return byId as HTMLInputElement
  if (d.name) {
    const byName = document.querySelector(`[name="${CSS.escape(d.name)}"]`)
    if (byName) return byName as HTMLInputElement
  }
  return f.el.isConnected ? (f.el as HTMLInputElement) : null
}

/** Some ATSes (Ashby's "autofill from résumé") parse the attached PDF and
 *  re-render the form a beat later, blanking values we wrote. Principle: be the
 *  last writer. Rather than guess a delay, watch the form settle and re-apply our
 *  fills on each mutation batch — ONLY where the field is now empty, so we never
 *  overwrite the user or the ATS's own parsed value (idempotent, no thrash). */
function reassertFills(fields: DetectedField[], plan: PlanItem[]): void {
  const byRef = new Map(fields.map((f) => [f.descriptor.field_ref, f]))
  const redo = () => {
    for (const item of plan) {
      if (item.action !== 'fill' || item.value == null || item.control === 'choice') continue
      const f = byRef.get(item.field_ref)
      const el = f && liveElement(f)
      if (el && isCombobox(el)) continue // comboboxes are re-driven by their own pass, never a raw re-write
      // A field the user touched is theirs. Re-writing "any empty field" meant
      // clearing a wrong autofill to retype it got the wrong value put straight
      // back, for the full 8s this observer runs.
      if (el && (userTouched(el) || el === document.activeElement)) continue
      if (!el || el.value.trim() !== '') continue
      // A <select> needs option matching, not a raw write: `item.value` is the
      // DISPLAY text ("Canada"), and assigning that to a select sets
      // selectedIndex -1 and blanks the control - so re-asserting after an ATS
      // re-render would silently destroy a correct selection.
      reapplyValue(el, item.value)
    }
  }
  let timer = 0
  const obs = new MutationObserver(() => {
    clearTimeout(timer)
    timer = window.setTimeout(redo, 250) // debounce bursts into one re-apply
  })
  obs.observe(document.body, { childList: true, subtree: true })
  redo() // once now, in case the form never re-renders
  setTimeout(() => obs.disconnect(), 8000) // bounded: stop once it has surely settled
}

/** T19 learning loop: teach the backend from the user's own fills. For any field
 *  we could NOT confidently map, if it already holds one of the user's profile
 *  values, that reveals its canonical — send the CATEGORY back (structure +
 *  canonical, NEVER the value) so the next run maps it from cache. Best-effort. */
function captureMappingCorrections(fields: DetectedField[], mappings: Map<number, Mapping>, profile: Profile): void {
  const descriptors = fields.map((f) => f.descriptor)
  for (const f of fields) {
    const m = mappings.get(f.descriptor.field_ref)
    if (m && m.canonical !== 'unknown' && m.confidence >= FILL_THRESHOLD) continue // already confidently mapped
    const value = (('value' in f.el ? (f.el as HTMLInputElement).value : '') || '').trim()
    if (!value) continue
    const canonical = reverseCanonical(value, profile)
    if (!canonical) continue
    sendToBackground({
      type: 'CORRECT',
      host: location.host,
      fields: descriptors, // structure only
      field_ref: f.descriptor.field_ref,
      corrected_canonical: canonical, // the category — never the value
    }).catch(() => {}) // a missed correction just means we re-learn next run
  }
}

let stepWatcher: MutationObserver | null = null
// Every field any fill has detected on this page, by structural key.
const seenFields = new Set<string>()

/** After the first Fill, re-run detect→map→fill each time a Workday-style
 *  multi-step wizard advances to a NEW step. The user drives navigation (Save &
 *  Continue) — we NEVER advance or submit, we just re-fill the page they land on.
 *  A new step is a field we have NEVER seen. A field merely hiding or coming back
 *  is not one: Greenhouse's react-select sets its input to opacity 0 once
 *  answered, and treating that as a new step re-ran the fill over the user's
 *  edits. Debounced, so it never loops on fill()'s own DOM writes.
 *  ponytail: one observer for the page session. */
function watchSteps(jobId: string | null): void {
  if (stepWatcher) return // install once
  let busy = false
  let timer = 0
  stepWatcher = new MutationObserver(() => {
    clearTimeout(timer)
    timer = window.setTimeout(async () => {
      if (busy) return
      if (fieldKeys(detectFields(document)).every((k) => seenFields.has(k))) return // still the same step
      busy = true
      try {
        await fill(jobId)
      } finally {
        busy = false
      }
    }, 400) // debounce the wizard's render burst into one re-fill
  })
  stepWatcher.observe(document.body, { childList: true, subtree: true })
}

/** Answer Yes/No/choice radio groups deterministically (T17). Anchors each
 *  group's proof mark on its question block. Only records a mark when we filled
 *  it or it's a required question we couldn't answer — never per-option noise. */
function fillChoices(startRef: number, profile: Profile): { fields: DetectedField[]; plan: PlanItem[] } {
  const fields: DetectedField[] = []
  const plan: PlanItem[] = []
  for (const g of detectRadioGroups(document, startRef)) {
    const base = { field_ref: g.field_ref, label: g.question || g.name, canonical: 'free_text' as const }
    let item: PlanItem | null = null
    if (anyChecked(g.options.map((o) => o.el))) {
      item = { ...base, action: 'flag', reason: YOURS }
    } else {
      const d = decideChoice(g, profile)
      if (d.option) {
        selectRadio(d.option.el)
        item = { ...base, action: 'fill', value: d.option.label, needsReview: d.needsReview, reason: d.reason, control: 'choice' }
      } else if (g.required) {
        item = { ...base, action: 'blank', reason: d.reason ?? 'answer this yourself' }
      }
    }
    if (!item) continue // leave non-required, unanswerable groups unmarked (no clutter)
    fields.push({
      el: g.container,
      descriptor: {
        field_ref: g.field_ref, tag: 'fieldset', type: 'radio', name: g.name, id: '',
        autocomplete: '', aria_label: '', placeholder: '', label: g.question,
        data_automation_id: '', required: g.required,
      },
    })
    plan.push(item)
  }
  return { fields, plan }
}

/** Fill each free-text screening question via the backend answerer (T13). Each
 *  item is mutated in place: → 'fill' (with an AI-draft badge), 'blank', or
 *  'flag'. Guards: never overwrite the user's own input, respect maxlength,
 *  and stay idempotent (a re-Fill sees our prior answer and skips). */
async function answerFreeText(fields: DetectedField[], plan: PlanItem[], jobId: string | null): Promise<void> {
  const byRef = new Map(fields.map((f) => [f.descriptor.field_ref, f.el]))
  for (const item of plan) {
    if (item.action !== 'answer') continue
    const node = byRef.get(item.field_ref)
    if (!node) {
      item.action = 'flag'
      continue
    }
    // A dropdown holds a FIXED option list, so a drafted sentence is never a valid
    // value there. The option-matching drivers in apply.ts only handle action
    // 'fill', so an 'answer' item reaches neither of them and would be written raw.
    if (!acceptsFreeText(node)) {
      item.action = 'blank'
      item.reason = 'a dropdown - pick this one yourself'
      continue
    }
    const el = node as HTMLInputElement | HTMLTextAreaElement
    // Never type into the box the user is working in, or one they have already
    // touched - `alreadyFilled` only catches a field with text still in it, so a
    // field they just CLEARED to retype would otherwise be written under them.
    if (el === document.activeElement || userTouched(el)) {
      item.action = 'blank'
      item.reason = 'left for you - you were editing'
      continue
    }
    if (alreadyFilled(el)) {
      item.action = 'flag'
      item.reason = YOURS
      continue
    }
    let res: AnswerResult
    try {
      res = await sendToBackground<AnswerResult>({
        type: 'ANSWER',
        question: item.label,
        jobId,
        host: location.host,
      })
    } catch {
      item.action = 'flag'
      item.reason = "couldn't reach the answerer — answer this yourself"
      continue
    }
    if (!res.answer) {
      // A free-text question we TRIED but couldn't answer is a blank the user
      // must fill — show it as a visible "needs you" caret, not a generic flag
      // (those are now collapsed to a popup count). Never-auto / high-stakes ones
      // stay a flag so they surface as the distinct "sensitive" mark.
      const sensitive = /high-stakes|leave this to yourself|sensitive/i.test(item.reason ?? res.reason ?? '')
      item.action = sensitive ? 'flag' : 'blank'
      item.reason = res.reason ?? 'answer this yourself'
      continue
    }
    // The answer took a backend round-trip; the user may have typed here meanwhile.
    if (el === document.activeElement || userTouched(el) || alreadyFilled(el)) {
      item.action = 'flag'
      item.reason = YOURS
      continue
    }
    const value = fitMaxLength(el, res.answer)
    setNativeValue(el, value)
    item.action = 'fill'
    item.value = value
    item.needsReview = res.needs_review
    item.source = res.source
  }
}

async function getResume(jobId: string): Promise<File | null> {
  try {
    const { base64, filename } = await sendToBackground<PdfPayload>({ type: 'GET_PDF', jobId })
    const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0))
    return new File([bytes], filename, { type: 'application/pdf' })
  } catch {
    return null
  }
}

function group(plan: PlanItem[]): FillResult {
  return {
    filled: plan.filter((p) => p.action === 'fill'),
    attached: plan.filter((p) => p.action === 'attach'),
    blank: plan.filter((p) => p.action === 'blank'),
    flagged: plan.filter((p) => p.action === 'flag'),
  }
}

function empty(error: string): FillResult {
  return { filled: [], attached: [], blank: [], flagged: [], error }
}

startAutoApply({
  doc: document,
  href: location.href,
  fill,
  claim: (pageUrl) => sendToBackground({ type: 'AUTO_APPLY_CLAIM', pageUrl }),
  finish: (jobId, body) => sendToBackground({
    type: 'AUTO_APPLY_FINISH',
    jobId,
    submitted: body.submitted,
    unknownRequired: body.unknown_required,
    blocked: body.blocked,
  }),
  profile: () => sendToBackground({ type: 'GET_PROFILE' }),
})
