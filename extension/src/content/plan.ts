import { FILL_THRESHOLD } from '../shared/config'
import type { Canonical, Descriptor, Mapping, PlanItem, Profile } from '../shared/types'
import { screeningWant } from './choice-answer'

/** The value that goes in a canonical field — ALWAYS from the profile, never
 *  invented. Returns null when the profile has nothing (→ leave blank). */
function valueFor(c: Canonical, p: Profile): string | null {
  const parts = (p.name || '').trim().split(/\s+/).filter(Boolean)
  switch (c) {
    case 'full_name':
      return p.name?.trim() || null
    case 'first_name':
      return parts[0] || null
    case 'last_name':
      return parts.length > 1 ? parts.slice(1).join(' ') : null
    case 'email':
      return p.email || null
    case 'phone':
      return p.phone || null
    case 'location':
      return p.location || null
    case 'work_authorization':
      return p.work_auth || null
    case 'linkedin':
      return p.links?.linkedin || null
    case 'github':
      return p.links?.github || null
    case 'portfolio':
    case 'website':
      return p.links?.portfolio || null
    default:
      // address (granular subfield), years_experience, cover_letter, free_text, unknown, resume_upload
      return null // → left BLANK; we never fill a value we don't hold
  }
}

/** The canonical a field's CURRENT value reveals, by matching it against the
 *  user's OWN profile values (T19 learning loop). Lets the extension infer "the
 *  user typed their email here" and send only that CATEGORY back as a correction
 *  — the value itself never leaves the page. null when nothing matches. */
export function reverseCanonical(value: string, p: Profile): Canonical | null {
  const v = value.trim().toLowerCase()
  if (!v) return null
  const eq = (x?: string | null): boolean => !!x && x.trim().toLowerCase() === v
  if (eq(p.email)) return 'email'
  if (eq(p.phone)) return 'phone'
  if (eq(p.links?.linkedin)) return 'linkedin'
  if (eq(p.links?.github)) return 'github'
  if (eq(p.links?.portfolio)) return 'portfolio'
  if (eq(p.location)) return 'location'
  if (eq(p.work_auth)) return 'work_authorization'
  if (eq(p.name)) return 'full_name'
  const parts = (p.name || '').trim().split(/\s+/).filter(Boolean)
  if (parts[0] && eq(parts[0])) return 'first_name'
  if (parts.length > 1 && eq(parts.slice(1).join(' '))) return 'last_name'
  return null
}

/** Decide, per field, what to do — the trust boundary. The mapper says what a
 *  field *means*; this decides whether we have a value and dare to write it. */
export function planFill(
  ds: Descriptor[],
  mappings: Map<number, Mapping>,
  profile: Profile,
  hasResume: boolean,
  opts: { threshold?: number } = {},
): PlanItem[] {
  const threshold = opts.threshold ?? FILL_THRESHOLD
  const out: PlanItem[] = []
  for (const d of ds) {
    const m = mappings.get(d.field_ref)
    const canonical: Canonical = m?.canonical ?? 'unknown'
    const confidence = m?.confidence ?? 0
    const base = { field_ref: d.field_ref, label: d.label || d.name || d.id || '(field)', canonical }

    // T19: a screening/demographic <select> or combobox is answered by the T17
    // policy (Yes/No/demographic from the user's OWN self-ID, always flagged for
    // review) over whatever widget it is — not the factual mapper. Non-screening
    // dropdowns (country/state) fall through to the canonical logic below.
    if (d.tag === 'combobox' || d.tag === 'select') {
      const want = screeningWant(base.label, profile)
      if (want) {
        if (want.text) out.push({ ...base, action: 'fill', value: want.text, needsReview: true, reason: want.reason, control: 'choice' })
        else out.push({ ...base, action: 'blank', reason: want.reason ?? 'answer this yourself' })
        continue
      }
    }

    if (canonical === 'resume_upload') {
      out.push({ ...base, action: hasResume ? 'attach' : 'blank', reason: hasResume ? undefined : 'no tailored résumé selected' })
      continue
    }
    // free-text screening question → answered by the backend answerer (T13).
    if (canonical === 'free_text') {
      // ...but only where a drafted sentence is a legal value. A dropdown has a
      // FIXED option list: Greenhouse renders School / Degree / Discipline as
      // react-select `<input role=combobox>`, and the LLM mapper labels them
      // free_text because no education canonical exists. Answering one wrote
      // visible prose into the control and made no real selection.
      if (d.tag === 'combobox' || d.tag === 'select') {
        out.push({ ...base, action: 'blank', reason: 'a dropdown - pick this one yourself' })
        continue
      }
      out.push({ ...base, action: 'answer' })
      continue
    }
    // cover letter is a separate, bigger ticket — leave it to the user.
    if (canonical === 'cover_letter') {
      out.push({ ...base, action: 'flag', reason: 'answer this yourself' })
      continue
    }
    if (canonical === 'unknown') {
      // skip quietly unless required — then surface it so nothing is missed
      if (d.required) out.push({ ...base, action: 'flag', reason: 'not recognized — fill yourself' })
      continue
    }
    if (confidence < threshold) {
      out.push({ ...base, action: 'flag', reason: 'unsure what this field wants' })
      continue
    }
    const value = valueFor(canonical, profile)
    if (value == null) out.push({ ...base, action: 'blank', reason: 'no saved value in your profile' })
    else out.push({ ...base, action: 'fill', value })
  }
  return out
}
