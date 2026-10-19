import { describe, expect, test, vi } from 'vitest'

import { canAutoSubmit, runAutoApply, submitIfAllowed, unknownRequired } from '../src/content/auto-apply'

const openGate = {
  enabled: true,
  applyUrl: 'https://jobs.lever.co/acme/1',
  resumeReady: true,
  unknownRequired: [] as string[],
  blocked: null,
}

describe('auto-apply gate', () => {
  test('switch default is a closed gate', () => {
    const form = document.createElement('form')
    form.requestSubmit = vi.fn()
    const result = submitIfAllowed(form, { ...openGate, enabled: false }, () => {})
    expect(result.ok).toBe(false)
    expect(form.requestSubmit).not.toHaveBeenCalled()
  })

  test('unknown required fields block submit', () => {
    const labels = unknownRequired(
      [{ field_ref: 0, label: 'Visa', action: 'flag', canonical: 'unknown' }],
      [{ field_ref: 0, required: true, label: 'Visa' }],
    )
    expect(labels).toEqual(['Visa'])
    const decision = canAutoSubmit({ ...openGate, unknownRequired: labels })
    expect(decision.ok).toBe(false)
    const form = document.createElement('form')
    form.requestSubmit = vi.fn()
    submitIfAllowed(form, { ...openGate, unknownRequired: labels }, () => {})
    expect(form.requestSubmit).not.toHaveBeenCalled()
  })

  test('a captcha blocks submit', () => {
    const decision = canAutoSubmit({ ...openGate, blocked: 'captcha' })
    expect(decision.ok).toBe(false)
    if (!decision.ok) expect(decision.reason.toLowerCase()).toContain('captcha')
  })
})

describe('runAutoApply', () => {
  test('does not finish as submitted when a required field is unknown', async () => {
    const form = document.createElement('form')
    form.requestSubmit = vi.fn()
    document.body.append(form)
    const finish = vi.fn(async () => ({}))
    const result = await runAutoApply({
      doc: document,
      href: 'https://jobs.lever.co/acme/1',
      claim: async () => ({ job_id: 'abc', apply_url: 'https://jobs.lever.co/acme/1' }),
      fill: async () => ({ unknownRequired: ['Visa'] }),
      profile: async () => ({ auto_apply: true }),
      finish,
      say: () => {},
    })
    expect(result).toBe('stopped')
    expect(form.requestSubmit).not.toHaveBeenCalled()
    expect(finish).toHaveBeenCalledWith('abc', expect.objectContaining({ submitted: false, unknown_required: ['Visa'] }))
    form.remove()
  })

  test('idle when nothing is armed', async () => {
    const fill = vi.fn()
    const result = await runAutoApply({
      doc: document,
      href: 'https://jobs.lever.co/acme/1',
      claim: async () => ({ job_id: null, apply_url: null }),
      fill,
      profile: async () => ({ auto_apply: true }),
      finish: async () => ({}),
      say: () => {},
    })
    expect(result).toBe('idle')
    expect(fill).not.toHaveBeenCalled()
  })
})
