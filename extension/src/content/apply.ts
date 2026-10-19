import { YOURS } from '../shared/mark-kind'
import type { PlanItem } from '../shared/types'
import type { DetectedField } from './detector'
import { preservingFocus, preservingPageScroll, userHasTakenOver, userTouched } from './takeover'

type Valued = HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement

/** Set a field's value the way a real keystroke would, so React/Vue-controlled
 *  ATS forms register it: write through the native setter (bypassing the
 *  framework's value shim), then dispatch bubbling input + change events. */
export function setNativeValue(el: Valued, value: string): void {
  const proto =
    el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : el instanceof HTMLSelectElement
        ? HTMLSelectElement.prototype
        : HTMLInputElement.prototype
  const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set
  const previous = el.value
  if (setter) setter.call(el, value)
  else el.value = value
  // React caches the last value in a hidden `_valueTracker`. If that cache still
  // equals our new value, React treats the write as a no-op and never fires
  // onChange — so a later re-render (e.g. Ashby's "autofill from résumé" re-parse)
  // reverts our text. Rewind the tracker to the previous value so React sees a
  // real change and commits it to state. (jsdom/no-React → tracker undefined, skip.)
  const tracker = (el as unknown as { _valueTracker?: { setValue(v: string): void } })._valueTracker
  if (tracker) tracker.setValue(previous)
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
}

/** Normalize option/label text for tolerant matching: lowercase, punctuation →
 *  space, collapse whitespace. So "United States" matches "United States of
 *  America". */
function norm(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
}

/** Pick the candidate matching `value`: exact normalized match on its text (or
 *  optional alt text like an <option> value) wins; else the UNIQUE candidate
 *  whose text CONTAINS the value. Returns null on no match OR ambiguity — never
 *  guess a wrong option on a submitted application. Shared by <select> +
 *  combobox (T19). */
export function pickOption<T>(items: T[], value: string, textOf: (t: T) => string, altOf?: (t: T) => string): T | null {
  const want = norm(value)
  if (!want) return null
  const exact = items.find((it) => norm(textOf(it)) === want || (altOf ? norm(altOf(it)) === want : false))
  if (exact) return exact
  const contains = items.filter((it) => norm(textOf(it)).includes(want))
  return contains.length === 1 ? contains[0] : null
}

/** Select the <option> matching `value`. Returns false (leaves the select
 *  untouched) on no match/ambiguity, so the caller flags it — never a wrong pick. */
export function setSelectValue(el: HTMLSelectElement, value: string): boolean {
  // skip the empty / "Select One" placeholder option — it is never an answer.
  const opts = [...el.options].filter((o) => o.value !== '' && norm(o.text) !== 'select one')
  const match = pickOption(opts, value, (o) => o.text, (o) => o.value)
  if (!match) return false
  setNativeValue(el, match.value)
  return true
}

/** Select one radio option the way a real click would (T17). Native `checked`
 *  setter (bypass the framework shim) + a bubbling click/change so React/Vue
 *  radio groups register the choice. Radios never toggle off, so this is safe. */
export function selectRadio(el: HTMLInputElement): void {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'checked')?.set
  if (setter) setter.call(el, true)
  else el.checked = true
  el.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  el.dispatchEvent(new Event('input', { bubbles: true }))
  el.dispatchEvent(new Event('change', { bubbles: true }))
}

/** True when the user already picked an option in this group — never overwrite it. */
export function anyChecked(els: HTMLInputElement[]): boolean {
  return els.some((el) => el.checked)
}

/** Attach a File to an <input type=file> via DataTransfer (the only way to set
 *  .files programmatically), then fire change so the form picks it up. */
export function attachFile(input: HTMLInputElement, file: File): void {
  const dt = new DataTransfer()
  dt.items.add(file)
  input.files = dt.files
  input.dispatchEvent(new Event('input', { bubbles: true }))
  input.dispatchEvent(new Event('change', { bubbles: true }))
}

/** True when the user already answered — we never overwrite their input. Also
 *  makes re-Fill idempotent: our own prior answer counts as "already there". */
export function alreadyFilled(el: Valued): boolean {
  return el.value.trim().length > 0
}

/** Clamp to the field's maxlength so an AI draft can never exceed a hard cap.
 *  ponytail: honors the maxlength attribute only; fuzzy "max N words" hints in
 *  label prose are deferred until a real form needs them. */
export function fitMaxLength(el: HTMLInputElement | HTMLTextAreaElement, text: string): string {
  const max = el.maxLength
  return max > 0 && text.length > max ? text.slice(0, max) : text
}

/** True for an ARIA combobox trigger (Workday Country/State/Phone-type): an
 *  element that opens a listbox popup. Its options live outside it, so it needs
 *  the async open→type→pick flow below, not a plain value write. */
export function isCombobox(el: Element): boolean {
  return el.matches('[role="combobox"], [aria-haspopup="listbox"]')
}

/** THIS combobox's own popup — never "whatever listbox is on the page".
 *
 *  Verified live on job-boards.greenhouse.io (2026-09-22): an open Greenhouse
 *  form carries the phone widget's country listbox (`iti-0__country-listbox`,
 *  244 options: "Afghanistan+93", "Åland Islands+358", …) in the DOM at ALL
 *  times, and it comes FIRST in document order. So a bare
 *  `document.querySelector('[role=listbox]')` returned the country list for every
 *  control on the page — Degree's own popup holds 10 options
 *  ("Bachelor's Degree", …) while the global query saw 354. Matching a value
 *  against another control's options is how you select a phone country code
 *  nobody asked for.
 *
 *  ARIA's `aria-controls`/`aria-owns` is the association, and react-select sets
 *  `aria-controls="react-select-<id>-listbox"` when it opens. When neither is
 *  present we look only inside the trigger's own field container — and if that
 *  finds nothing we return null rather than fall back to the document, because a
 *  wrong popup is worse than no fill (the caller then blanks + flags). */
export function popupFor(trigger: Element, before: ReadonlySet<Element> = new Set()): Element | null {
  const doc = trigger.ownerDocument
  // 1. The ARIA association, when the widget publishes one. Authoritative.
  const id = trigger.getAttribute('aria-controls') || trigger.getAttribute('aria-owns')
  if (id) {
    const owned = doc.getElementById(id)
    if (owned) return owned.matches('[role="listbox"]') ? owned : (owned.querySelector('[role="listbox"]') ?? owned)
  }
  // 2. A listbox inside the trigger's own field wrapper, if it wasn't already there.
  const scope = trigger.closest('.field, fieldset, [data-automation-id], li, [class*="select"]')
  const scoped = scope?.querySelector('[role="listbox"]')
  if (scoped && !before.has(scoped)) return scoped
  // 3. A listbox that APPEARED since we opened this one. This is what separates a
  //    real popup from an always-mounted widget like Greenhouse's phone-country
  //    list. Ambiguity (two new popups) means we cannot tell — take neither.
  const fresh = [...doc.querySelectorAll('[role="listbox"]')].filter((l) => !before.has(l))
  return fresh.length === 1 ? fresh[0] : null
}

/** Listboxes already mounted before we open ours — the baseline for `popupFor`. */
export function listboxSnapshot(doc: Document = document): ReadonlySet<Element> {
  return new Set(doc.querySelectorAll('[role="listbox"]'))
}

/** The selectable rows of one popup. Scoped, for the same reason as `popupFor`. */
export function optionsIn(popup: Element | null): HTMLElement[] {
  return popup ? [...popup.querySelectorAll<HTMLElement>('[role="option"]')] : []
}

/** Re-apply a kept value to a live element after an ATS re-render. A <select>
 *  must go through option matching: `value` is the DISPLAY text ("Canada"), and
 *  assigning that straight to a select sets selectedIndex -1 and BLANKS it - so
 *  the re-assert pass would destroy the very selection it is meant to protect. */
export function reapplyValue(el: Valued, value: string): void {
  if (el instanceof HTMLSelectElement) setSelectValue(el, value)
  else setNativeValue(el, value)
}

/** Can this control hold an arbitrary drafted sentence? A dropdown cannot: it has
 *  a FIXED option list, so free text either blanks it (native <select> sets
 *  selectedIndex -1) or, on a react-select `<input role=combobox>` as Greenhouse
 *  uses for School / Degree / Discipline, leaves visible prose with no real
 *  selection made. Those must be left for the user, never written. */
export function acceptsFreeText(el: Element): boolean {
  return !isCombobox(el) && !(el instanceof HTMLSelectElement)
}

/** Poll `get` until it returns truthy or the timeout elapses — the popup listbox
 *  renders a beat after the trigger opens, and re-filters a beat after typing.
 *  Small and dependency-free. */
async function waitFor<T>(get: () => T | null, timeoutMs = 2000, stepMs = 50): Promise<T | null> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const v = get()
    if (v) return v
    if (Date.now() >= deadline) return null
    await new Promise((r) => setTimeout(r, stepMs))
  }
}

/** Drive an ARIA combobox to `value` (T19, the Workday lane): open the popup,
 *  type into its search box if present (typeahead), wait for the listbox, then
 *  click the option whose text exactly/uniquely matches. Returns false — closing
 *  the popup, leaving the field untouched — on no match or ambiguity; NEVER a
 *  blind first-row pick. Timing/DOM varies per ATS, so this is the piece that
 *  MUST be live-verified. */
export async function fillCombobox(trigger: HTMLElement, value: string): Promise<boolean> {
  // Interact via dispatched pointer EVENTS (never the direct click method — the
  // no-submit guard forbids it). NOTE: this is an educated-guess hardening from a
  // live Workday run where the dropdown OPENED but never selected. Two likely
  // causes addressed: (1) the option list is VIRTUALIZED — only visible rows are
  // in the DOM — so we type into the search to filter our match into existence;
  // (2) rows select on the full mouse sequence, not a lone click. LIVE-VERIFY on
  // a real Workday form is still required to confirm.
  const mouse = (el: Element, ...types: string[]): void => {
    for (const t of types) el.dispatchEvent(new MouseEvent(t, { bubbles: true }))
  }
  const close = (): void => {
    trigger.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
  }

  // The user outranks us: never open a popup over someone who is already typing.
  if (userHasTakenOver()) return false

  // Baseline BEFORE opening, so an always-mounted widget (Greenhouse's phone
  // country listbox) can never be mistaken for this control's popup.
  const before = listboxSnapshot(trigger.ownerDocument)
  mouse(trigger, 'mousedown', 'mouseup', 'click') // open the listbox popup
  const listbox = await waitFor(() => popupFor(trigger, before))
  if (!listbox) return false

  // Typeahead: type the value into the popup search so a virtualized list filters
  // down until our match actually renders into the DOM. On react-select (Greenhouse)
  // the trigger IS the text input, so it doubles as its own search box.
  const search = (listbox.querySelector('input') ??
    listbox.parentElement?.querySelector('input') ??
    (trigger instanceof HTMLInputElement ? trigger : null)) as HTMLInputElement | null
  // On react-select the trigger IS the text input, so typing to filter writes into
  // the VISIBLE field. Remember what was there: if no option matches we must put it
  // back, or a failed drive leaves our search string sitting in the control -
  // which is the "prose left in the School box" bug wearing a different hat.
  const searchWas = search ? search.value : ''
  const restoreSearch = (): void => {
    if (search && search.value !== searchWas) setNativeValue(search, searchWas)
  }
  if (search) {
    // Restore the caret afterwards — focusing the popup's search box mid-sentence
    // is exactly how the fill used to steal typing out from under the user.
    preservingFocus(() => {
      search.focus()
      setNativeValue(search, value)
      search.dispatchEvent(new KeyboardEvent('keyup', { key: value.slice(-1) || 'a', bubbles: true }))
    })
  }

  // Wait for the exact/unique MATCH to be present (post-filter) — not just any option.
  const match = await waitFor(() => {
    if (userHasTakenOver()) return null // stand down mid-drive
    const opts = optionsIn(popupFor(trigger, before) ?? listbox).filter(
      (o) => (o.textContent ?? '').trim() && norm(o.textContent ?? '') !== 'select one',
    )
    return opts.length ? pickOption(opts, value, (o) => o.textContent ?? '') : null
  })
  if (!match) {
    restoreSearch() // undo our typeahead text before backing out
    close() // no confident match → leave the field untouched, never a wrong/first-row pick
    return false
  }

  // A virtualized row must be in view to receive events, but scrollIntoView moves
  // every scrollable ancestor INCLUDING the document. Put the page back.
  preservingPageScroll(() => match.scrollIntoView?.({ block: 'nearest' }))
  mouse(match, 'mousedown', 'mouseup', 'click') // select on the full pointer sequence, not click alone

  // Confirm it COMMITTED instead of reporting an optimistic success. Measured
  // live on react-select: a committed pick closes the popup (aria-expanded goes
  // "true" -> "false") and the search input returns to EMPTY, with the chosen
  // label rendered as separate text - so the input's own value is not the
  // signal, and a click that quietly did nothing would otherwise be reported as
  // filled while our typeahead text sat in the control. Widgets that publish no
  // aria-expanded (Workday's button comboboxes) are trusted exactly as before.
  const committed = await waitFor(() => (trigger.getAttribute('aria-expanded') !== 'true' ? true : null), 1000)
  if (!committed) {
    restoreSearch()
    close()
    return false
  }
  return true
}

/** Execute a fill plan against the detected elements. 'blank'/'flag' items are
 *  deliberately left untouched — we never write a value we're unsure of.
 *  Comboboxes are skipped here — the async pass (fillComboboxes) handles them. */
export function applyPlan(fields: DetectedField[], plan: PlanItem[], resume: File | null): void {
  const byRef = new Map(fields.map((f) => [f.descriptor.field_ref, f.el]))
  for (const item of plan) {
    const el = byRef.get(item.field_ref)
    if (!el) continue
    // A field the user worked is theirs, on every pass. A re-fill used to write
    // our value straight back over their edit (live Greenhouse: "NA" -> "F1").
    // Flagged, not blanked, so no "needs you" mark lands on their answer. Runs
    // before the combobox skip, so the async pass never opens theirs either.
    if ((item.action === 'fill' || item.action === 'attach') && userTouched(el)) {
      item.action = 'flag'
      item.value = undefined
      item.reason = YOURS
      continue
    }
    if (item.action === 'fill' && item.value != null) {
      if (isCombobox(el)) continue // async combobox pass owns these
      if (el instanceof HTMLSelectElement) {
        // A dropdown needs option-matching, not a raw value write (P2). No option
        // matched → downgrade to blank + flag; never leave a wrong selection.
        if (!setSelectValue(el, item.value)) {
          item.action = 'blank'
          item.value = undefined
          item.reason = "couldn't match a dropdown option — pick it yourself"
        }
      } else {
        setNativeValue(el as Valued, item.value)
      }
    } else if (item.action === 'attach' && resume) attachFile(el as HTMLInputElement, resume)
  }
}

/** Async fill pass for ARIA comboboxes (T19). Runs after applyPlan; mutates each
 *  combobox 'fill' item to blank + flag when the option can't be matched, so an
 *  unmatched combobox is never left in a wrong state. */
export async function fillComboboxes(fields: DetectedField[], plan: PlanItem[]): Promise<void> {
  const byRef = new Map(fields.map((f) => [f.descriptor.field_ref, f.el]))
  for (const item of plan) {
    if (item.action !== 'fill' || item.value == null) continue
    const el = byRef.get(item.field_ref)
    if (!el || !isCombobox(el)) continue
    // Once the user is working the form, stop driving the rest. Each remaining
    // combobox would open a popup, focus its search box and scroll a row into
    // view - on a 16-combobox Greenhouse form that is up to a minute of the page
    // moving under someone who is already correcting our earlier fills.
    if (userHasTakenOver()) {
      item.action = 'blank'
      item.value = undefined
      item.reason = 'left for you - you were editing'
      continue
    }
    if (!(await fillCombobox(el as HTMLElement, item.value))) {
      item.action = 'blank'
      item.value = undefined
      item.reason = "couldn't match a dropdown option — pick it yourself"
    }
  }
}
