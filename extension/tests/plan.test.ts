import { describe, expect, test } from 'vitest'

import { planFill, reverseCanonical } from '../src/content/plan'
import type { Canonical, Descriptor, Mapping, Profile } from '../src/shared/types'

const profile: Profile = {
  name: 'Ada Lovelace',
  email: 'ada@analytical.io',
  phone: '555-0100',
  location: 'London, UK',
  work_auth: 'Authorized to work in the UK',
  links: {
    linkedin: 'https://linkedin.com/in/ada',
    github: 'https://github.com/ada',
    portfolio: 'https://ada.dev',
  },
}

function d(field_ref: number, over: Partial<Descriptor> = {}): Descriptor {
  return {
    field_ref,
    tag: 'input',
    type: 'text',
    name: '',
    id: '',
    autocomplete: '',
    aria_label: '',
    placeholder: '',
    label: '',
    data_automation_id: '',
    required: false,
    ...over,
  }
}
function mp(field_ref: number, canonical: Canonical, confidence = 0.95): Mapping {
  return { field_ref, canonical, confidence, source: 'heuristic' }
}
function plan(ds: Descriptor[], ms: Mapping[], hasResume = false) {
  return planFill(ds, new Map(ms.map((m) => [m.field_ref, m])), profile, hasResume)
}

describe('planFill (fill decisions — the trust boundary)', () => {
  test('derives first/last name from the single profile name', () => {
    const p = plan([d(0), d(1)], [mp(0, 'first_name'), mp(1, 'last_name')])
    expect(p[0]).toMatchObject({ action: 'fill', value: 'Ada' })
    expect(p[1]).toMatchObject({ action: 'fill', value: 'Lovelace' })
  })

  test('fills links, location, and work authorization from profile', () => {
    const p = plan(
      [d(0), d(1), d(2), d(3)],
      [mp(0, 'linkedin'), mp(1, 'location'), mp(2, 'work_authorization'), mp(3, 'portfolio')],
    )
    expect(p.map((x) => x.value)).toEqual([
      'https://linkedin.com/in/ada',
      'London, UK',
      'Authorized to work in the UK',
      'https://ada.dev',
    ])
  })

  test('address subfields are left BLANK, never the coarse location (T19 "Long Beach in postal code" fix)', () => {
    const p = plan(
      [d(0, { label: 'Postal Code' }), d(1, { label: 'City' })],
      [mp(0, 'address'), mp(1, 'location')],
    )
    expect(p[0].action).toBe('blank') // postal code: no wrong value inherited from location
    expect(p[0].value).toBeUndefined()
    expect(p[1]).toMatchObject({ action: 'fill', value: 'London, UK' }) // a genuine city still fills
  })

  test('a mapped field with no profile value is left BLANK, never guessed', () => {
    const p = plan([d(0, { label: 'Years of experience' })], [mp(0, 'years_experience')])
    expect(p[0].action).toBe('blank')
    expect(p[0].value).toBeUndefined()
  })

  test('low-confidence mapping is left blank AND flagged', () => {
    const p = plan([d(0, { label: 'Ambiguous' })], [mp(0, 'email', 0.4)])
    expect(p[0].action).toBe('flag')
  })

  test('free_text questions route to the answerer; cover_letter stays with the user (T13)', () => {
    expect(plan([d(0, { tag: 'textarea', label: 'Why here?' })], [mp(0, 'free_text', 0.6)])[0].action).toBe('answer')
    expect(plan([d(0, { type: 'file', label: 'Cover letter' })], [mp(0, 'cover_letter')])[0].action).toBe('flag')
  })

  test('resume_upload attaches when a résumé exists, else blank', () => {
    const ds = [d(0, { type: 'file', label: 'Resume' })]
    expect(plan(ds, [mp(0, 'resume_upload')], true)[0].action).toBe('attach')
    expect(plan(ds, [mp(0, 'resume_upload')], false)[0].action).toBe('blank')
  })

  test('screening combobox routes through T17 (Yes/No from self-ID), always flagged (T19)', () => {
    const eligible: Profile = { ...profile, work_eligible: 'yes' }
    const p = planFill(
      [d(0, { tag: 'combobox', label: 'Are you legally authorized to work in the country?' })],
      new Map(),
      eligible,
      false,
    )
    expect(p[0]).toMatchObject({ action: 'fill', value: 'yes', control: 'choice', needsReview: true })
  })

  test('screening combobox with no profile self-ID → blank, never guessed (T19)', () => {
    const p = plan([d(0, { tag: 'combobox', label: 'Are you legally authorized to work?' })], [])
    expect(p[0].action).toBe('blank')
  })

  test('a non-screening dropdown (Country) stays factual, not routed to T17 (T19)', () => {
    const p = plan([d(0, { tag: 'combobox', label: 'Country' })], [mp(0, 'location')])
    expect(p[0]).toMatchObject({ action: 'fill', value: 'London, UK' })
  })

  test('a consent/terms checkbox is flagged, NEVER auto-accepted (trust boundary, T19)', () => {
    const p = plan(
      [d(0, { type: 'checkbox', required: true, label: 'Yes, I acknowledge that I have read and understand the policy.' })],
      [mp(0, 'unknown', 0.2)],
    )
    expect(p[0].action).toBe('flag') // surfaced for the user; we never accept terms on their behalf
    expect(p[0].value).toBeUndefined()
  })

  test('unknown non-required fields are skipped; unknown required is flagged', () => {
    const p = plan(
      [d(0, { required: false }), d(1, { required: true })],
      [mp(0, 'unknown', 0.2), mp(1, 'unknown', 0.2)],
    )
    expect(p.find((x) => x.field_ref === 0)).toBeUndefined()
    expect(p.find((x) => x.field_ref === 1)!.action).toBe('flag')
  })
})

describe('reverseCanonical (T19 learning loop: infer the category from a landed value)', () => {
  test('matches a profile value back to its canonical', () => {
    expect(reverseCanonical('ada@analytical.io', profile)).toBe('email')
    expect(reverseCanonical('555-0100', profile)).toBe('phone')
    expect(reverseCanonical('https://github.com/ada', profile)).toBe('github')
    expect(reverseCanonical('London, UK', profile)).toBe('location')
    expect(reverseCanonical('Ada Lovelace', profile)).toBe('full_name')
    expect(reverseCanonical('Ada', profile)).toBe('first_name')
    expect(reverseCanonical('Lovelace', profile)).toBe('last_name')
  })

  test('is case/whitespace tolerant', () => {
    expect(reverseCanonical('  ADA@ANALYTICAL.IO ', profile)).toBe('email')
  })

  test('returns null when nothing in the profile matches (never guesses)', () => {
    expect(reverseCanonical('some unrelated answer', profile)).toBe(null)
    expect(reverseCanonical('', profile)).toBe(null)
  })
})

describe('free_text never targets a dropdown (Phase 1)', () => {
  // Greenhouse has no education canonical, so the backend LLM labels School /
  // Degree / Discipline `free_text` at confidence 0.8 - above FILL_THRESHOLD.
  // Planning an 'answer' for those wrote a drafted sentence straight into a
  // react-select combobox. Verified live: 2445 of ~2831 cached Greenhouse field
  // mappings are free_text, so this is the dominant path on that ATS.
  test('a combobox mapped free_text is blanked and flagged, never answered', () => {
    const items = plan([d(0, { tag: 'combobox', type: 'combobox', id: 'school--0', label: 'School' })], [mp(0, 'free_text', 0.8)])
    expect(items[0].action).toBe('blank')
    expect(items[0].action).not.toBe('answer')
    expect(items[0].reason).toMatch(/dropdown/i)
  })

  test('a native <select> mapped free_text is blanked too', () => {
    const items = plan([d(0, { tag: 'select', type: 'select', label: 'Degree' })], [mp(0, 'free_text', 0.8)])
    expect(items[0].action).toBe('blank')
  })

  test('a real textarea question is STILL answered (the fix must not break screening answers)', () => {
    const items = plan([d(0, { tag: 'textarea', type: 'textarea', label: 'Why do you want to work here?' })], [mp(0, 'free_text', 0.6)])
    expect(items[0].action).toBe('answer')
  })

  test('a plain text input mapped free_text is STILL answered', () => {
    // Ashby renders short-answer questions as <input type=text>, not textarea.
    const items = plan([d(0, { tag: 'input', type: 'text', label: 'Describe a project' })], [mp(0, 'free_text', 0.8)])
    expect(items[0].action).toBe('answer')
  })
})
