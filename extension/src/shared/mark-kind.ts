// Which proof mark a planned field earns (T15). One shared classifier for the
// on-page layer and the popup review list, so a field is never marked one way on
// the page and another in the summary. Reads only the signals T12/T13 emit —
// the flag sub-types come off the answerer's reason string (its only tell).
import type { PlanItem } from './types'

/** The reason on a field the user already answered themselves. No mark on the
 *  page, and never counted as a field we "couldn't map" in the popup. */
export const YOURS = 'you already answered this'

export type MarkKind = 'draft' | 'choice' | 'ok' | 'blank' | 'sensitive' | 'query' | 'flag'

export function markKind(item: PlanItem): MarkKind {
  if (item.action === 'attach') return 'ok'
  if (item.action === 'fill') {
    if (!item.needsReview) return 'ok'
    // a radio/select selection we made → "review this pick", not the text editor
    return item.control === 'choice' ? 'choice' : 'draft'
  }
  if (item.action === 'blank') return 'blank'
  return flagKind(item) // 'flag' + any 'answer' left unresolved
}

/** Sub-type a flagged field. Sensitive wins first — a demographic/high-stakes
 *  question must never be softened into a benign "check this". */
export function flagKind(item: PlanItem): 'sensitive' | 'query' | 'flag' {
  const r = (item.reason || '').toLowerCase()
  if (/high-stakes|sensitive|demographic|eeo|leave this to yourself/.test(r)) return 'sensitive'
  if (/unsure|not recognized|recognize|confidence/.test(r)) return 'query'
  return 'flag'
}
