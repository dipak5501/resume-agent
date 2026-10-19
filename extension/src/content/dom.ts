// Shared DOM/text helpers for the content-script field detectors — the bits
// detector.ts (text fields) and choices.ts (radio groups) both need, written
// once so the label-lookup escaping and marker-stripping can't drift apart.

/** Collapse whitespace and strip required-marker glyphs (*, ✱) from label text. */
export function clean(s: string): string {
  return s.replace(/[*✱]/g, ' ').replace(/\s+/g, ' ').trim()
}

/** The cleaned text of an explicitly associated `<label for=id>`, or null. The
 *  id is CSS-escaped so quotes/backslashes in it can't break the selector. */
export function labelByFor(el: Element): string | null {
  if (!el.id) return null
  const l = el.ownerDocument.querySelector(`label[for="${el.id.replace(/["\\]/g, '\\$&')}"]`)
  return l?.textContent ? clean(l.textContent) : null
}
