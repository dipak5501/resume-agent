import type { Descriptor } from '../shared/types'
import { clean, labelByFor } from './dom'

export interface DetectedField {
  el: HTMLElement
  descriptor: Descriptor
}

const FILLABLE = 'input, select, textarea'
// input types that are never profile-fillable text/file fields. 'radio' is
// excluded here because radio *groups* are detected separately (T17 choices.ts)
// as one logical Yes/No/choice question, not one field per option.
const SKIP_TYPES = new Set(['submit', 'button', 'reset', 'hidden', 'image', 'radio'])

// ARIA combobox trigger (T19): Workday Country/State/Phone-type etc. — a control
// that opens a listbox popup. Filled via the async open→type→pick path (apply.ts),
// so it is detected here but written differently.
const COMBOBOX = '[role="combobox"], button[aria-haspopup="listbox"]'

/** Read every fillable field on the page into a structure-only Descriptor.
 *  Pure DOM read — no chrome APIs — so it unit-tests in jsdom over fixtures. */
export function detectFields(root: Document | Element = document): DetectedField[] {
  const out: DetectedField[] = []
  for (const el of root.querySelectorAll<HTMLElement>(FILLABLE)) {
    const tag = el.tagName.toLowerCase()
    const type = (el.getAttribute('type') || (tag === 'input' ? 'text' : tag)).toLowerCase()
    if (tag === 'input' && SKIP_TYPES.has(type)) continue
    if (el.matches(COMBOBOX)) continue // an <input role=combobox> is handled by the combobox pass below
    // Never touch a CAPTCHA response field (e.g. Ashby's hidden g-recaptcha-response).
    if (/captcha/i.test(`${el.getAttribute('name') || ''} ${el.id}`)) continue
    if (isHoneypot(el)) continue // bot-trap fields: writing them flags us as a bot
    if (!isVisible(el)) continue
    out.push({
      el,
      descriptor: {
        field_ref: out.length,
        tag,
        type,
        name: el.getAttribute('name') || '',
        id: el.id || '',
        autocomplete: el.getAttribute('autocomplete') || '',
        aria_label: el.getAttribute('aria-label') || '',
        placeholder: el.getAttribute('placeholder') || '',
        label: labelFor(el),
        data_automation_id: el.getAttribute('data-automation-id') || '',
        required: el.hasAttribute('required') || el.getAttribute('aria-required') === 'true',
        context: contextFor(el),
      },
    })
  }
  for (const el of root.querySelectorAll<HTMLElement>(COMBOBOX)) {
    if (!isFormCombobox(el) || !isVisible(el)) continue
    out.push({
      el,
      descriptor: {
        field_ref: out.length,
        tag: 'combobox',
        type: 'combobox',
        name: el.getAttribute('name') || '',
        id: el.id || '',
        autocomplete: '',
        // NEVER el's aria-label: on Workday it embeds the current VALUE
        // ("Country United States of America Required"), a privacy-boundary leak.
        aria_label: '',
        placeholder: '',
        label: comboboxLabel(el),
        data_automation_id: el.getAttribute('data-automation-id') || '',
        required: el.getAttribute('aria-required') === 'true',
        context: contextFor(el),
      },
    })
  }
  return out
}

/** The structural key of each detected field (T19 multi-step). Stable across
 *  value fills and proof-mark overlays (structure, never values), so a wizard's
 *  new step shows up as keys never seen before. */
export function fieldKeys(fields: DetectedField[]): string[] {
  return fields.map((f) => `${f.descriptor.tag}:${f.descriptor.type}:${f.descriptor.name}:${f.descriptor.label}`)
}

/** A combobox that belongs to the application form — not a nav/utility menu
 *  (Workday's "Settings" is also a `button[aria-haspopup=listbox]`). Scoped to a
 *  form / the Workday apply flow, or carrying a field-level required flag. */
function isFormCombobox(el: HTMLElement): boolean {
  if (el.closest('nav, header, [role="navigation"], [role="menubar"]')) return false
  return el.closest('form, [data-automation-id="applyFlowPage"]') !== null || el.getAttribute('aria-required') === 'true'
}

/** Structural label for a combobox — NEVER its aria-label (which on Workday
 *  embeds the current value). Workday renders a single-field combobox with a
 *  nearby `<label>` (Country) and a screening combobox inside a `<fieldset>`
 *  whose `<legend>` is the question — resolve both, structurally. */
function comboboxLabel(el: HTMLElement): string {
  const byFor = labelByFor(el)
  if (byFor) return byFor
  const legend = el.closest('fieldset')?.querySelector('legend')?.textContent
  if (legend?.trim()) return clean(legend)
  const lbl = el.closest('.field, [data-automation-id], fieldset, li')?.querySelector('label')
  return lbl?.textContent ? clean(lbl.textContent) : ''
}

function isVisible(el: HTMLElement): boolean {
  if (el.hidden) return false
  const cs = el.ownerDocument.defaultView?.getComputedStyle(el)
  if (!cs) return true
  if (cs.display === 'none' || cs.visibility === 'hidden') return false
  // opacity:0 hides a field the way honeypots do — BUT it's also the normal
  // pattern for a résumé <input type=file> sitting invisibly under a styled
  // "Attach résumé" button (Lever, Greenhouse). Only reject opacity:0 for
  // non-file fields; the honeypot guard (name/aria) still covers file traps.
  const isFile = el.tagName === 'INPUT' && (el.getAttribute('type') || '').toLowerCase() === 'file'
  if (cs.opacity === '0' && !isFile) return false
  return true
}

// Honeypots are decoy fields hidden from humans; only bots fill them. Skip the
// common tells: a name/id/class trap word, or an aria-hidden wrapper. (display/
// visibility/opacity hiding is caught by isVisible.)
const HONEYPOT = /honeypot|bot[-_]?field|hp[-_]?field|confirm[-_]?email/i
function isHoneypot(el: HTMLElement): boolean {
  const sig = `${el.getAttribute('name') || ''} ${el.id} ${el.className}`
  if (HONEYPOT.test(sig)) return true
  return el.closest('[aria-hidden="true"]') !== null
}

const HEADING = 'h1, h2, h3, h4, h5, h6, [role="heading"]'

/** Structure-only nearby signal for the LLM mapping lane (T19): the enclosing
 *  fieldset legend + the nearest section heading above the field. Drawn ONLY
 *  from heading/legend elements — never from inputs or their values — so no
 *  entered value can cross the privacy boundary. Capped so the payload stays small. */
function contextFor(el: HTMLElement): string {
  const parts: string[] = []
  const legend = el.closest('fieldset')?.querySelector('legend')?.textContent
  if (legend?.trim()) parts.push(clean(legend))
  const heading = nearestHeading(el)
  if (heading && !parts.includes(heading)) parts.push(heading)
  return parts.join(' · ').slice(0, 200)
}

/** The nearest section heading preceding the field: scan previous siblings up
 *  the ancestor chain, heading elements only (structural, never a value). */
function nearestHeading(el: Element): string {
  for (let node: Element | null = el; node && node !== document.body; node = node.parentElement) {
    for (let sib = node.previousElementSibling; sib; sib = sib.previousElementSibling) {
      if (sib.matches(HEADING) && sib.textContent?.trim()) return clean(sib.textContent)
    }
  }
  return ''
}

/** Resolve the human label for a field, trying the reliable signals first. */
function labelFor(el: HTMLElement): string {
  const forLabel = labelByFor(el)
  if (forLabel) return forLabel
  const wrap = el.closest('label')
  if (wrap?.textContent) return clean(wrap.textContent)

  const ref = el.getAttribute('aria-labelledby')
  if (ref) {
    const text = clean(
      ref
        .split(/\s+/)
        .map((id) => el.ownerDocument.getElementById(id)?.textContent || '')
        .join(' '),
    )
    if (text) return text
  }
  const aria = el.getAttribute('aria-label')
  if (aria) return clean(aria)

  const container = el.closest('.field, .application-field, .application-question, li, fieldset, div, p')
  const label = container?.querySelector('label')
  if (label?.textContent) return clean(label.textContent)

  return clean(el.getAttribute('placeholder') || '')
}
