// The whole content-script fill, end to end in jsdom: the REAL index.ts wired to a
// stubbed `chrome`, replaying what was measured live on a Greenhouse form (Telnyx,
// 2026-09-23). There, picking any react-select option hides its input
// (opacity 0), which used to read as "a new wizard step" and re-run the fill -
// and the re-fill wrote our "F1" back over the user's "NA".
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'

import type { FillResult, Profile } from '../src/shared/types'

type Msg = { type: string; question?: string }
type Reply = (resp: unknown) => void

const PROFILE: Profile = { email: 'ada@analytical.io', work_auth: 'F1', needs_sponsorship: 'no' }

let calls: Msg[]
let onAnswer: (reply: Reply) => void
let fill: () => Promise<FillResult>
let userEdits: (el: HTMLInputElement | HTMLTextAreaElement, value: string) => void

const tick = (ms: number) => new Promise((r) => setTimeout(r, ms))
async function until(ok: () => boolean, ms = 5000): Promise<void> {
  for (const end = Date.now() + ms; !ok(); await tick(10)) if (Date.now() > end) throw new Error('timed out')
}
const count = (type: string) => calls.filter((c) => c.type === type).length
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T

// A fresh body strands a test's observers (index.ts never disconnects the step
// watcher) on a detached node, so they can't fire into the next test or teardown.
afterEach(() => document.body.replaceWith(document.createElement('body')))

beforeEach(async () => {
  vi.resetModules()
  calls = []
  onAnswer = (reply) => reply({ answer: null, reason: 'none' })
  let listener: (msg: unknown, sender: unknown, respond: (r: FillResult) => void) => void = () => {}
  ;(globalThis as unknown as { chrome: unknown }).chrome = {
    runtime: {
      lastError: undefined,
      onMessage: { addListener: (fn: typeof listener) => (listener = fn) },
      sendMessage: (msg: Msg, reply: Reply) => {
        calls.push(msg)
        if (msg.type === 'ANSWER') return onAnswer(reply)
        const resp = msg.type === 'GET_PROFILE' ? PROFILE : msg.type === 'MAP_FIELDS' ? { mappings: [] } : {}
        setTimeout(() => reply(resp), 0)
      },
    },
  }
  await import('../src/content/index')
  const { noteUserActivity } = await import('../src/content/takeover')
  fill = () => new Promise((res) => listener({ type: 'FILL', jobId: null }, {}, res))
  userEdits = (el, value) => {
    noteUserActivity(el) // the trusted keydown the real listener would have seen
    el.value = value
  }
})

/** A react-select dropdown as Greenhouse renders it: once an option is picked the
 *  input goes to opacity 0 and the chosen label renders beside it. */
function reactSelect(id: string, label: string, options: string[]): string {
  return `<div class="field"><label for="${id}">${label}</label><input id="${id}" role="combobox" aria-expanded="false" data-options="${options.join('|')}" /></div>`
}
function wireReactSelect(el: HTMLInputElement): void {
  el.addEventListener('click', () => {
    if (el.parentElement!.querySelector('[role=listbox]')) return
    el.setAttribute('aria-expanded', 'true')
    const lb = document.createElement('div')
    lb.setAttribute('role', 'listbox')
    for (const o of el.dataset.options!.split('|')) {
      const opt = document.createElement('div')
      opt.setAttribute('role', 'option')
      opt.textContent = o
      opt.addEventListener('click', () => pick(el, o))
      lb.appendChild(opt)
    }
    el.parentElement!.appendChild(lb)
  })
}
function pick(el: HTMLInputElement, text: string): void {
  el.parentElement!.querySelector('[role=listbox]')?.remove()
  el.setAttribute('aria-expanded', 'false')
  el.style.opacity = '0'
  const shown = document.createElement('div')
  shown.className = 'single-value'
  shown.textContent = text
  el.parentElement!.appendChild(shown)
}
function clearPick(el: HTMLInputElement): void {
  el.parentElement!.querySelector('.single-value')?.remove()
  el.style.opacity = '1'
}

const DEBOUNCE_PLUS = 700 // watchSteps debounces 400 ms, then fill() makes its round-trips

describe('a fill never undoes what the user changed', () => {
  test('Greenhouse replay: picking a dropdown after editing our answer keeps the edit, and is not a new step', async () => {
    document.body.innerHTML = `<form>
      ${reactSelect('loc', 'Location (City)', ['Long Beach, California, United States'])}
      <label for="q">If "yes" to the previous questions, what is the basis of your current work authorization and when does it expire?</label>
      <textarea id="q"></textarea>
    </form>`
    wireReactSelect($('loc'))
    await fill()
    expect($<HTMLTextAreaElement>('q').value).toBe('F1') // what the live form got

    userEdits($('q'), 'NA')
    userEdits($('loc'), '')
    pick($('loc'), 'Long Beach, California, United States')
    await tick(DEBOUNCE_PLUS)
    expect($<HTMLTextAreaElement>('q').value).toBe('NA')
    expect(count('GET_PROFILE')).toBe(1) // no re-fill: a hidden input is not a new step

    clearPick($('loc')) // the user clears the pick: the input is visible again
    await tick(DEBOUNCE_PLUS)
    expect(count('GET_PROFILE')).toBe(1) // a field coming BACK is not a new step either
  })

  test('a dropdown WE answered (and so hid) is not a new step when the user clears it', async () => {
    document.body.innerHTML = `<form>${reactSelect('sp', 'Do you now or in the future require Visa sponsorship?', ['Yes', 'No'])}</form>`
    wireReactSelect($('sp'))
    const res = await fill()
    expect(res.filled.map((f) => f.value)).toEqual(['no']) // the driver picked it...
    expect($<HTMLInputElement>('sp').style.opacity).toBe('0') // ...so it was hidden before watchSteps started

    userEdits($('sp'), '')
    clearPick($('sp'))
    await tick(DEBOUNCE_PLUS)
    expect(count('GET_PROFILE')).toBe(1)
    expect($('sp').parentElement!.querySelector('[role=listbox]')).toBeNull() // never re-opened under the user
  })

  test('a real new step still re-fills - its new fields only, never the user edit', async () => {
    document.body.innerHTML = `<form id="f">
      <label for="q">What is your work authorization?</label><textarea id="q"></textarea>
    </form>`
    await fill()
    userEdits($('q'), 'NA')

    $('f').insertAdjacentHTML('beforeend', '<label for="e">Email</label><input id="e" />')
    await until(() => $<HTMLInputElement>('e').value !== '') // the wizard lane still works
    expect(count('GET_PROFILE')).toBe(2)
    expect($<HTMLInputElement>('e').value).toBe('ada@analytical.io')
    expect($<HTMLTextAreaElement>('q').value).toBe('NA')
  })

  test('typing while the drafted answer is in flight: the typed text wins', async () => {
    document.body.innerHTML = `<form>
      <label for="p">Tell us about a project you are proud of</label><textarea id="p"></textarea>
    </form>`
    let release: Reply = () => {}
    onAnswer = (reply) => (release = reply)
    const done = fill()
    await until(() => count('ANSWER') > 0)

    userEdits($('p'), 'my own words')
    release({ answer: 'A drafted answer', source: 'llm', needs_review: true })
    const res = await done
    expect($<HTMLTextAreaElement>('p').value).toBe('my own words')
    expect(res.filled).toEqual([]) // never reported as ours
  })
})
