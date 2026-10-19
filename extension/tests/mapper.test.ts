import { describe, expect, test } from 'vitest'

import { detectFields } from '../src/content/detector'
import { mapAll, mapDescriptor } from '../src/content/mapper'
import type { Canonical, Descriptor } from '../src/shared/types'
import { bare, loadFixture } from './util'

function canonicalBySelector(pick: (d: Descriptor) => boolean): Canonical {
  const ds = detectFields(document).map((f) => f.descriptor)
  const target = ds.find(pick)!
  const map = new Map(mapAll(ds).map((m) => [m.field_ref, m]))
  return map.get(target.field_ref)!.canonical
}

describe('mapAll (deterministic heuristic)', () => {
  test('greenhouse: identity/contact/file fields map by autocomplete + type', () => {
    loadFixture('greenhouse.html')
    expect(canonicalBySelector((d) => d.name === 'first_name')).toBe('first_name')
    expect(canonicalBySelector((d) => d.name === 'last_name')).toBe('last_name')
    expect(canonicalBySelector((d) => d.name === 'email')).toBe('email')
    expect(canonicalBySelector((d) => d.name === 'phone')).toBe('phone')
    expect(canonicalBySelector((d) => d.name === 'resume')).toBe('resume_upload')
    expect(canonicalBySelector((d) => d.name === 'cover_letter')).toBe('cover_letter')
  })

  test('greenhouse: label-only variations resolve (LinkedIn, years-exp, free text)', () => {
    loadFixture('greenhouse.html')
    expect(canonicalBySelector((d) => d.id === 'q_linkedin')).toBe('linkedin')
    expect(canonicalBySelector((d) => d.id === 'q_experience')).toBe('years_experience')
    expect(canonicalBySelector((d) => d.id === 'q_why')).toBe('free_text')
  })

  test('ashby: bare "Name", system email/résumé, uuid LinkedIn; autofill dropzone skipped', () => {
    loadFixture('ashby.html')
    expect(canonicalBySelector((d) => d.id === '_systemfield_name')).toBe('full_name')
    expect(canonicalBySelector((d) => d.id === '_systemfield_email')).toBe('email')
    expect(canonicalBySelector((d) => d.id === '_systemfield_resume')).toBe('resume_upload')
    expect(canonicalBySelector((d) => d.label === 'LinkedIn profile URL')).toBe('linkedin')
    // the anonymous autofill file input must NOT be classified as the résumé field
    const ds = detectFields(document).map((f) => f.descriptor)
    const anon = ds.find((d) => d.type === 'file' && !d.id && !d.name)!
    const map = new Map(mapAll(ds).map((m) => [m.field_ref, m]))
    expect(map.get(anon.field_ref)!.canonical).toBe('unknown')
  })

  test('workday: data-automation-id is the SOLE signal (no label/aria/name)', () => {
    // The real Workday hard case: inputs whose only meaningful attribute is the
    // automation-id. camelCase/underscore compounds, so word-boundary label
    // rules miss them — needs dedicated substring matching.
    expect(mapDescriptor(bare({ data_automation_id: 'legalNameSection_firstName' })).canonical).toBe('first_name')
    expect(mapDescriptor(bare({ data_automation_id: 'legalNameSection_lastName' })).canonical).toBe('last_name')
    expect(mapDescriptor(bare({ data_automation_id: 'email' })).canonical).toBe('email')
    expect(mapDescriptor(bare({ data_automation_id: 'phone-number' })).canonical).toBe('phone')
    expect(mapDescriptor(bare({ data_automation_id: 'addressSection_city' })).canonical).toBe('location')
    expect(mapDescriptor(bare({ data_automation_id: 'linkedinQuestion' })).canonical).toBe('linkedin')
    expect(mapDescriptor(bare({ type: 'file', data_automation_id: 'file-upload-input-ref' })).canonical).toBe('resume_upload')
  })

  test('workday: fields resolve by data-automation-id even with no name/id', () => {
    loadFixture('workday.html')
    expect(canonicalBySelector((d) => d.data_automation_id === 'legalNameSection_firstName')).toBe('first_name')
    expect(canonicalBySelector((d) => d.data_automation_id === 'legalNameSection_lastName')).toBe('last_name')
    expect(canonicalBySelector((d) => d.data_automation_id === 'email')).toBe('email')
    expect(canonicalBySelector((d) => d.data_automation_id === 'phone-number')).toBe('phone')
    expect(canonicalBySelector((d) => d.data_automation_id === 'addressSection_city')).toBe('location')
    expect(canonicalBySelector((d) => d.data_automation_id === 'file-upload-input-ref')).toBe('resume_upload')
    expect(canonicalBySelector((d) => d.data_automation_id === 'freeFormQuestion')).toBe('free_text')
  })

  test('file inputs: résumé attaches by keyword; a generic custom file question does not', () => {
    // the real résumé field (Lever name="resume") → attach
    expect(mapDescriptor(bare({ type: 'file', name: 'resume', id: 'resume-upload-input' })).canonical).toBe('resume_upload')
    // Lever custom "Upload file" question (named, but no résumé tell) → leave for the user,
    // never attach the résumé to the wrong slot
    expect(mapDescriptor(bare({ type: 'file', name: 'cards[uuid][field0]', label: 'Upload file' })).canonical).toBe('unknown')
  })

  test('lever: single full-name field + urls[Network] links + unknown company', () => {
    loadFixture('lever.html')
    expect(canonicalBySelector((d) => d.name === 'name')).toBe('full_name')
    expect(canonicalBySelector((d) => d.name === 'urls[LinkedIn]')).toBe('linkedin')
    expect(canonicalBySelector((d) => d.name === 'urls[GitHub]')).toBe('github')
    expect(canonicalBySelector((d) => d.name === 'urls[Portfolio]')).toBe('portfolio')
    expect(canonicalBySelector((d) => d.name === 'org')).toBe('unknown')
    expect(canonicalBySelector((d) => d.name === 'comments')).toBe('free_text')
  })
})
