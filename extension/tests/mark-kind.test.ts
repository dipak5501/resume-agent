import { describe, expect, it } from 'vitest'

import { flagKind, markKind } from '../src/shared/mark-kind'
import type { PlanItem } from '../src/shared/types'

const item = (p: Partial<PlanItem>): PlanItem => ({
  field_ref: 0,
  label: 'f',
  canonical: 'free_text',
  action: 'flag',
  ...p,
})

describe('markKind', () => {
  it('maps actions to the right proof mark', () => {
    expect(markKind(item({ action: 'attach' }))).toBe('ok')
    expect(markKind(item({ action: 'fill', needsReview: false }))).toBe('ok')
    expect(markKind(item({ action: 'fill', needsReview: true }))).toBe('draft') // AI draft
    expect(markKind(item({ action: 'blank' }))).toBe('blank')
  })

  it('sub-types flags off the answerer reason', () => {
    expect(markKind(item({ reason: 'high-stakes — leave this to yourself' }))).toBe('sensitive')
    expect(markKind(item({ reason: 'unsure what this field wants' }))).toBe('query')
    expect(markKind(item({ reason: 'answer this yourself' }))).toBe('flag')
    expect(markKind(item({ reason: undefined }))).toBe('flag')
  })

  it('never softens a sensitive field into a benign mark', () => {
    // even if a low-confidence tell is also present, sensitive must win
    expect(flagKind(item({ reason: 'high-stakes, unsure' }))).toBe('sensitive')
  })
})
