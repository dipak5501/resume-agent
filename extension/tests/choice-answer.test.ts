import { describe, expect, it } from 'vitest'

import { classifyQuestion, decideChoice, matchOption } from '../src/content/choice-answer'
import type { ChoiceGroup, ChoiceOption } from '../src/content/choices'
import type { Profile } from '../src/shared/types'

const opt = (label: string, value = label): ChoiceOption => ({
  label,
  value,
  el: document.createElement('input') as HTMLInputElement,
})
const group = (question: string, labels: string[], required = true): ChoiceGroup => ({
  field_ref: 0,
  name: 'q',
  question,
  required,
  options: labels.map((l) => opt(l)),
  container: document.createElement('div'),
})
const YESNO = ['Yes', 'No']

describe('classifyQuestion', () => {
  it('routes screening questions to categories', () => {
    expect(classifyQuestion('Are you legally eligible to work in the US?')).toBe('work_eligible')
    expect(classifyQuestion('Will you now or in the future require visa sponsorship for H1?')).toBe('sponsorship')
    expect(classifyQuestion('Do you have a disability?')).toBe('disability')
    expect(classifyQuestion('Are you a protected veteran?')).toBe('veteran')
    expect(classifyQuestion('Have you ever been convicted of a felony?')).toBe('criminal')
    expect(classifyQuestion('Are you subject to any non-compete agreement?')).toBe('legal_restriction')
    expect(classifyQuestion('What is your favorite color?')).toBe('other')
  })
})

describe('decideChoice — defaults & sourcing', () => {
  it('fills work eligibility from the profile, flagged for review', () => {
    const d = decideChoice(group('Are you eligible to work in the US?', YESNO), { work_eligible: 'yes' })
    expect(d.option?.label).toBe('Yes')
    expect(d.needsReview).toBe(true)
  })

  it('defaults criminal / legal / disability / veteran to No and ALWAYS flags review', () => {
    for (const q of [
      'Have you ever been convicted of a felony?',
      'Are you subject to a non-compete agreement?',
      'Do you have a disability?',
      'Are you a protected veteran?',
    ]) {
      const d = decideChoice(group(q, ['Yes', 'No']), {})
      expect(d.option?.label).toBe('No')
      expect(d.needsReview).toBe(true) // sensitive → never silent
      expect(d.reason).toMatch(/confirm/i)
    }
  })

  it('uses the real value over the default when the user has set one', () => {
    const d = decideChoice(group('Are you a veteran?', ['Yes', 'No']), { veteran: 'yes' })
    expect(d.option?.label).toBe('Yes')
  })

  it('leaves unknown questions and unset facts alone (no guessing)', () => {
    expect(decideChoice(group('Which team interests you?', ['Platform', 'Growth']), {}).option).toBeNull()
    // work eligibility with nothing stored → cannot answer, points to the profile
    const d = decideChoice(group('Eligible to work in the US?', YESNO), {})
    expect(d.option).toBeNull()
    expect(d.reason).toMatch(/profile/i)
  })
})

describe('matchOption — label variants', () => {
  const p: Profile = {}
  it('matches No / decline against verbose EEO option labels', () => {
    const opts = [opt('Yes, I have a disability'), opt("No, I don't have a disability"), opt('I don’t wish to answer')]
    expect(matchOption(opts, 'no')?.label).toBe("No, I don't have a disability")
    expect(matchOption(opts, 'decline')?.label).toBe('I don’t wish to answer')
    void p
  })
  it('matches a demographic value by substring', () => {
    expect(matchOption([opt('Male'), opt('Female'), opt('Non-binary')], 'female')?.label).toBe('Female')
  })
})
