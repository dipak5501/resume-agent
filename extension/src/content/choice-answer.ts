// The screening-choice policy (T17). Deterministic — no LLM. Decides, for a
// radio/choice question, which option (if any) to pre-select from the user's own
// profile facts, and ALWAYS marks the sensitive ones for review. Never submits.
//
// Trust rules baked in here (do not soften without intent):
//  - work eligibility / sponsorship / gender / race → the user's OWN stated fact,
//    or nothing (never guessed).
//  - disability / veteran → the user's fact, else default "No" (a deliberate
//    product choice) — always flagged for review because "No" can be untrue.
//  - criminal / legal restrictions → default the negative, always flagged.
//  - anything else → leave it for the user.
import type { Profile } from '../shared/types'
import type { ChoiceGroup, ChoiceOption } from './choices'

export type Category =
  | 'work_eligible'
  | 'sponsorship'
  | 'gender'
  | 'race'
  | 'disability'
  | 'veteran'
  | 'criminal'
  | 'legal_restriction'
  | 'other'

// Order matters: the sensitive/specific patterns win before broad ones.
const RULES: [Category, RegExp][] = [
  ['sponsorship', /sponsor|require.*visa|visa.*sponsor|h-?1\b|h1-?b/],
  ['work_eligible', /eligible to work|authoriz(ed|ation) to work|legally.*work|right to work|work in the (us|u\.s|united states)/],
  ['disability', /disab/],
  ['veteran', /veteran|protected veteran|military service|armed forces/],
  ['gender', /\bgender\b|\bsex\b/],
  ['race', /\brace\b|ethnicit|hispanic|latino/],
  ['criminal', /felon|convict|criminal (record|history|background)|ever been (convicted|arrested)|plead(ed)? guilty/],
  ['legal_restriction', /non-?compete|restrictive covenant|litigation|non-?disclosure|restrict.*ability to (fully )?perform/],
]

export function classifyQuestion(q: string): Category {
  const s = q.toLowerCase()
  for (const [cat, re] of RULES) if (re.test(s)) return cat
  return 'other'
}

export interface Want {
  text: string | null // desired answer ('yes' | 'no' | 'decline' | a demographic value), null = leave it
  review: boolean
  reason?: string
}

const yesno = (v?: string | null): string | null => {
  const s = (v || '').trim().toLowerCase()
  if (['yes', 'y', 'true'].includes(s)) return 'yes'
  if (['no', 'n', 'false'].includes(s)) return 'no'
  if (/declin|prefer not|don.?t wish/.test(s)) return 'decline'
  return null
}

function wanted(cat: Category, p: Profile): Want {
  switch (cat) {
    case 'work_eligible':
      return { text: yesno(p.work_eligible), review: true, reason: whyReview(p.work_eligible, 'work eligibility') }
    case 'sponsorship':
      return { text: yesno(p.needs_sponsorship), review: true, reason: whyReview(p.needs_sponsorship, 'sponsorship') }
    case 'gender':
      return { text: p.gender?.trim() || null, review: true }
    case 'race':
      return { text: p.race?.trim() || null, review: true }
    // deliberate product choice: default the negative when unset, always review.
    case 'disability':
      return { text: yesno(p.disability) ?? 'no', review: true, reason: 'defaulted to No — confirm this is accurate' }
    case 'veteran':
      return { text: yesno(p.veteran) ?? 'no', review: true, reason: 'defaulted to No — confirm this is accurate' }
    case 'criminal':
    case 'legal_restriction':
      return { text: 'no', review: true, reason: 'defaulted to No — confirm this is accurate' }
    default:
      return { text: null, review: true }
  }
}

function whyReview(v: string | null | undefined, what: string): string | undefined {
  return yesno(v) ? undefined : `add your ${what} in your profile so this can fill`
}

/** The desired answer for a screening/demographic question, independent of the
 *  widget (T19): category from the question text, value from the user's OWN
 *  profile self-ID, always flagged for review. Returns null for a non-screening
 *  question (→ leave it to the factual mapper). Drives radios, <select>s AND
 *  comboboxes — the T17 policy, one source, three widgets. */
export function screeningWant(question: string, profile: Profile): Want | null {
  const cat = classifyQuestion(question)
  return cat === 'other' ? null : wanted(cat, profile)
}

/** Find the option that matches the wanted answer. Yes/No/decline match by the
 *  option's leading word (labels vary: "No", "No, I don't…"); a demographic
 *  value matches by substring against the option label. */
export function matchOption(options: ChoiceOption[], want: string): ChoiceOption | null {
  const opts = options.map((o) => ({ o, t: `${o.label} ${o.value}`.toLowerCase() }))
  const find = (re: RegExp) => opts.find(({ t }) => re.test(t))?.o ?? null
  if (want === 'yes') return find(/^\s*yes\b|\bi am\b|\bam\s+(authorized|eligible)\b/)
  if (want === 'no') return find(/^\s*no\b|\bi am not\b|\bdo not\b|\bdon.?t\b|\bnot\s+(authorized|eligible)\b/)
  if (want === 'decline') return find(/declin|prefer not|don.?t wish|do not wish|not to answer/)
  const w = want.toLowerCase()
  return opts.find(({ t }) => t.includes(w))?.o ?? null
}

export interface ChoiceDecision {
  option: ChoiceOption | null // the option to select, or null = leave it
  needsReview: boolean
  reason?: string
}

export function decideChoice(group: ChoiceGroup, profile: Profile): ChoiceDecision {
  const want = wanted(classifyQuestion(group.question), profile)
  if (!want.text) return { option: null, needsReview: true, reason: want.reason }
  const option = matchOption(group.options, want.text)
  if (!option)
    return { option: null, needsReview: true, reason: "couldn't match an option — choose it yourself" }
  return { option, needsReview: want.review, reason: want.reason }
}
