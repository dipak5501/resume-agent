// The user outranks the autofill (T12 trust boundary, extended).
//
// A fill runs for tens of seconds (a combobox drive per dropdown, then a backend
// round-trip per free-text field), so the user is correcting the first fields
// while the driver is still opening popups, focusing search boxes and scrolling
// rows into view. Watch for REAL user input and stand down when it arrives.
//
// `isTrusted` is the whole trick: our own dispatched events are always false per
// the DOM spec, so we can never mistake ourselves for the user. `focusin` is
// deliberately NOT watched - a programmatic .focus() can produce a trusted focus
// event, which would make us stand down against ourselves.

let takenOver = false
const touched = new WeakSet<Element>()
// ...and by stable identity as well. `liveElement` deliberately re-queries a
// field by id/name so an ATS re-render (Ashby re-parses the attached résumé and
// rebuilds the form) is still reachable - which hands us a NEW node the WeakSet
// has never seen. Without this, a field the user cleared to retype came back
// "untouched" and the re-assert pass wrote the wrong value straight back in.
const touchedKeys = new Set<string>()
let detach: (() => void) | null = null

/** The identity `liveElement` re-finds a field by, so a swapped node is still
 *  recognised as the user's. Empty when the field has neither id nor name. */
function keyOf(el: Element): string {
  const id = el.getAttribute('id')
  if (id) return `id:${id}`
  const name = el.getAttribute('name')
  return name ? `name:${name}` : ''
}

/** True once the user has actually typed, clicked, scrolled or touched. */
export function userHasTakenOver(): boolean {
  return takenOver
}

/** True if the user has interacted with this specific control - so we never
 *  re-write a field they just cleared in order to retype it. */
export function userTouched(el: Element | null | undefined): boolean {
  if (!el) return false
  if (touched.has(el)) return true
  const k = keyOf(el)
  return k !== '' && touchedKeys.has(k)
}

/** Record that the user is working the form. The event listener below is a thin
 *  wrapper over this; it is exported because jsdom defines `isTrusted` as an own
 *  non-configurable getter, so a test cannot forge a trusted event. Tests call
 *  this directly to exercise the consequences, and separately dispatch REAL
 *  synthetic events to prove the `isTrusted` guard rejects our own. */
export function noteUserActivity(target?: EventTarget | null): void {
  takenOver = true
  if (target instanceof Element) {
    const el = controlOf(target)
    touched.add(el)
    const k = keyOf(el)
    if (k) touchedKeys.add(k)
  }
}

// A hidden input (react-select renders one per `name`) is never something the user works.
const CONTROL = 'input:not([type="hidden"]), select, textarea, [role="combobox"], button[aria-haspopup="listbox"]'

/** The form control an event belongs to. A mouse-only dropdown pick never lands
 *  on the control: measured live on Greenhouse react-select, its two pointerdowns
 *  hit the arrow's <svg path> and the option <div>. So walk up to the nearest
 *  block holding exactly one control; a block holding several credits none. */
function controlOf(target: Element): Element {
  const own = target.closest(CONTROL)
  if (own) return own
  for (let n = target.parentElement; n && n !== target.ownerDocument.body; n = n.parentElement) {
    const found = n.querySelectorAll(CONTROL)
    if (found.length === 1) return found[0]
    if (found.length > 1) break
  }
  return target
}

/** Start watching. Idempotent; call at the top of each fill. */
export function watchTakeover(): void {
  stopWatchingTakeover()
  takenOver = false
  const on = (e: Event): void => {
    if (!e.isTrusted) return // our own dispatched events - never a takeover
    // Scrolling past a field is not working it: claiming it would stop
    // reassertFills restoring a value an ATS re-render blanked under the wheel.
    noteUserActivity(e.type === 'wheel' ? null : e.target)
  }
  // pointerdown/keydown/touchstart = the user is working the form.
  // wheel = the user is scrolling; moving the viewport under them is the bug.
  const types = ['pointerdown', 'keydown', 'wheel', 'touchstart'] as const
  for (const t of types) document.addEventListener(t, on, { capture: true, passive: true })
  detach = () => {
    for (const t of types) document.removeEventListener(t, on, { capture: true })
  }
}

function stopWatchingTakeover(): void {
  detach?.()
  detach = null
}

/** Run `fn` and put the page's scroll position back if it moved. A virtualized
 *  listbox row still needs scrollIntoView to receive events, but that scrolls
 *  every scrollable ancestor including the document. Restoring only the WINDOW
 *  keeps the listbox's own internal scroll (so the row stays reachable) while the
 *  page never moves under the user. */
export function preservingPageScroll<T>(fn: () => T): T {
  const x = window.scrollX
  const y = window.scrollY
  try {
    return fn()
  } finally {
    if (window.scrollX !== x || window.scrollY !== y) window.scrollTo(x, y)
  }
}

/** Run `fn` and restore whatever the user was focused on. The combobox driver
 *  focuses the popup's search box to drive typeahead; without this the caret is
 *  stolen mid-sentence. */
export function preservingFocus<T>(fn: () => T): T {
  const prev = document.activeElement
  // Only a control the user could actually be typing in is worth restoring.
  // Restoring to <body> (the usual case when nobody is typing) would BLUR the
  // widget we just focused - and react-select closes its menu on blur, so the
  // option we are about to pick would never be reachable.
  const worthRestoring =
    prev instanceof HTMLElement && (prev.matches('input, textarea, select') || prev.isContentEditable)
  try {
    return fn()
  } finally {
    if (worthRestoring && prev !== document.activeElement && prev instanceof HTMLElement) {
      prev.focus({ preventScroll: true })
    }
  }
}

/** Test seam only. */
export function resetTakeoverForTest(): void {
  stopWatchingTakeover()
  takenOver = false
  touchedKeys.clear()
}
