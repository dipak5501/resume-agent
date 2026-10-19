import { afterEach, describe, expect, test, vi } from 'vitest'

import { acceptsFreeText, alreadyFilled, applyPlan, fillCombobox, fillComboboxes, fitMaxLength, pickOption, reapplyValue, setNativeValue, setSelectValue } from '../src/content/apply'
import type { DetectedField } from '../src/content/detector'
import { noteUserActivity, resetTakeoverForTest, watchTakeover } from '../src/content/takeover'
import type { PlanItem } from '../src/shared/types'
import { bare } from './util'

describe('setNativeValue (React-controlled inputs need dispatched events)', () => {
  test('sets the value and dispatches input then change, bubbling', () => {
    document.body.innerHTML = '<input id="x" />'
    const el = document.getElementById('x') as HTMLInputElement
    const seen: string[] = []
    el.addEventListener('input', (e) => seen.push(`input:${e.bubbles}`))
    el.addEventListener('change', (e) => seen.push(`change:${e.bubbles}`))
    setNativeValue(el, 'ada@analytical.io')
    expect(el.value).toBe('ada@analytical.io')
    expect(seen).toEqual(['input:true', 'change:true'])
  })

  test('works on a textarea', () => {
    document.body.innerHTML = '<textarea id="t"></textarea>'
    const el = document.getElementById('t') as HTMLTextAreaElement
    setNativeValue(el, 'line one\nline two')
    expect(el.value).toBe('line one\nline two')
  })

  test('reaches the <select> prototype — but callers must NOT use it on a dropdown', () => {
    document.body.innerHTML =
      '<select id="s"><option value="">—</option><option value="us">United States</option></select>'
    const el = document.getElementById('s') as HTMLSelectElement
    const seen: string[] = []
    el.addEventListener('change', (e) => seen.push(`change:${e.bubbles}`))
    // setNativeValue is genuinely generic over the three value protos, and that
    // branch needs covering. It is NOT a licence to write a dropdown directly:
    // `us` works here only because it is an exact option VALUE. Real callers go
    // through setSelectValue / reapplyValue, because assigning display text
    // ("Canada") sets selectedIndex -1 and blanks the control.
    setNativeValue(el, 'us')
    expect(el.value).toBe('us')
    expect(el.selectedIndex).toBe(1)
    expect(seen).toEqual(['change:true'])
  })
})

describe('setSelectValue (P2: dropdown option matching)', () => {
  const sel = (html: string): HTMLSelectElement => {
    document.body.innerHTML = `<select id="s">${html}</select>`
    return document.getElementById('s') as HTMLSelectElement
  }

  test('exact normalized match sets the option and fires change', () => {
    const el = sel('<option value="">Select One</option><option value="us">United States of America</option><option value="ca">Canada</option>')
    const seen: string[] = []
    el.addEventListener('change', () => seen.push('change'))
    expect(setSelectValue(el, 'united states of america')).toBe(true)
    expect(el.value).toBe('us')
    expect(seen).toEqual(['change'])
  })

  test('unique contains-match wins ("United States" → "United States of America")', () => {
    const el = sel('<option value="">Select One</option><option value="us">United States of America</option><option value="ca">Canada</option>')
    expect(setSelectValue(el, 'United States')).toBe(true)
    expect(el.value).toBe('us')
  })

  test('matches by option value too (an exact code like "US")', () => {
    const el = sel('<option value="">-</option><option value="US">United States of America</option>')
    expect(setSelectValue(el, 'US')).toBe(true)
    expect(el.value).toBe('US')
  })

  test('no match leaves the placeholder selected and returns false', () => {
    const el = sel('<option value="">Select One</option><option value="fr">France</option>')
    expect(setSelectValue(el, 'Germany')).toBe(false)
    expect(el.value).toBe('') // never a wrong pick
  })

  test('ambiguous (multiple contains, no exact) → false, no guess', () => {
    const el = sel('<option value="">-</option><option value="n">New York</option><option value="y">York County</option>')
    expect(setSelectValue(el, 'York')).toBe(false)
  })

  test('never selects the empty / "Select One" placeholder', () => {
    const el = sel('<option value="">Select One</option><option value="y">Yes</option>')
    expect(setSelectValue(el, 'select one')).toBe(false)
  })
})

describe('applyPlan across widgets (P2)', () => {
  test('fills a matching <select>, downgrades an unmatched one to blank (never a wrong pick)', () => {
    document.body.innerHTML =
      '<select id="s1"><option value="">-</option><option value="ca">Canada</option></select>' +
      '<select id="s2"><option value="">-</option><option value="fr">France</option></select>'
    const s1 = document.getElementById('s1') as HTMLSelectElement
    const s2 = document.getElementById('s2') as HTMLSelectElement
    const fields: DetectedField[] = [
      { el: s1, descriptor: bare({ field_ref: 0, tag: 'select' }) },
      { el: s2, descriptor: bare({ field_ref: 1, tag: 'select' }) },
    ]
    const plan: PlanItem[] = [
      { field_ref: 0, label: 'Country', canonical: 'location', action: 'fill', value: 'Canada' },
      { field_ref: 1, label: 'Country', canonical: 'location', action: 'fill', value: 'Germany' },
    ]
    applyPlan(fields, plan, null)
    expect(s1.value).toBe('ca') // matched
    expect(plan[1].action).toBe('blank') // unmatched → downgraded
    expect(s2.value).toBe('') // untouched, no wrong selection
  })
})

describe('the user outranks every write path (re-fill after the user edited)', () => {
  afterEach(() => resetTakeoverForTest())

  test('applyPlan keeps what the user put in a text field or dropdown, and still fills the rest', () => {
    // Live Greenhouse (Telnyx): the user changed our "F1" to "NA"; a re-fill wrote "F1" straight back.
    document.body.innerHTML =
      '<textarea id="t">NA</textarea>' +
      '<select id="s"><option value="">-</option><option value="ca">Canada</option><option value="fr">France</option></select>' +
      '<input id="e" />'
    const t = document.getElementById('t') as HTMLTextAreaElement
    const s = document.getElementById('s') as HTMLSelectElement
    const e = document.getElementById('e') as HTMLInputElement
    s.value = 'fr'
    noteUserActivity(t)
    noteUserActivity(s)
    const fields: DetectedField[] = [
      { el: t, descriptor: bare({ field_ref: 0, tag: 'textarea' }) },
      { el: s, descriptor: bare({ field_ref: 1, tag: 'select' }) },
      { el: e, descriptor: bare({ field_ref: 2 }) },
    ]
    const plan: PlanItem[] = [
      { field_ref: 0, label: 'Work authorization', canonical: 'work_authorization', action: 'fill', value: 'F1' },
      { field_ref: 1, label: 'Country', canonical: 'location', action: 'fill', value: 'Canada' },
      { field_ref: 2, label: 'Email', canonical: 'email', action: 'fill', value: 'ada@analytical.io' },
    ]
    applyPlan(fields, plan, null)
    expect(t.value).toBe('NA')
    expect(s.value).toBe('fr')
    expect(e.value).toBe('ada@analytical.io') // an untouched field is still filled
    expect(plan.map((p) => p.action)).toEqual(['flag', 'flag', 'fill'])
    expect(plan[0].value).toBeUndefined() // the popup must not report "F1" as filled
  })

  test('a dropdown the user already worked is never opened by the async pass', async () => {
    document.body.innerHTML = '<input id="c" role="combobox" />'
    const c = document.getElementById('c') as HTMLInputElement
    let opened = false
    c.addEventListener('mousedown', () => (opened = true))
    noteUserActivity(c)
    watchTakeover() // a re-fill resets the page-wide takeover flag; the per-field memory must survive it
    const fields: DetectedField[] = [{ el: c, descriptor: bare({ field_ref: 0, tag: 'combobox' }) }]
    const plan: PlanItem[] = [{ field_ref: 0, label: 'Sponsorship', canonical: 'free_text', action: 'fill', value: 'no', control: 'choice' }]
    applyPlan(fields, plan, null) // the real order (index.ts): sync pass, then the async combobox pass
    await fillComboboxes(fields, plan)
    expect(opened).toBe(false)
    expect(plan[0].action).toBe('flag')
  })

  test('a file input the user picked their own file into is not re-attached', () => {
    // jsdom has no DataTransfer, so stand one in and watch the `files` write itself -
    // the test must fail on its assertion, not on a missing global.
    vi.stubGlobal('DataTransfer', class { items = { add() {} }; files = [] })
    document.body.innerHTML = '<input id="f" type="file" />'
    const f = document.getElementById('f') as HTMLInputElement
    const attached = vi.fn()
    Object.defineProperty(f, 'files', { set: attached })
    noteUserActivity(f)
    const plan: PlanItem[] = [{ field_ref: 0, label: 'Resume', canonical: 'resume_upload', action: 'attach' }]
    applyPlan([{ el: f, descriptor: bare({ field_ref: 0, type: 'file' }) }], plan, new File(['x'], 'resume.pdf'))
    expect(attached).not.toHaveBeenCalled()
    expect(plan[0].action).toBe('flag')
    vi.unstubAllGlobals()
  })
})

describe('pickOption (P2: the shared option matcher)', () => {
  const items = ['Canada', 'United States of America', 'United Kingdom']
  const id = (x: string) => x

  test('exact normalized match wins', () => {
    expect(pickOption(items, 'canada', id)).toBe('Canada')
  })
  test('unique contains-match wins', () => {
    expect(pickOption(items, 'United States', id)).toBe('United States of America')
  })
  test('ambiguous (multiple contain, no exact) → null', () => {
    expect(pickOption(items, 'United', id)).toBe(null) // both "United ..." contain it
  })
  test('no match → null', () => {
    expect(pickOption(items, 'France', id)).toBe(null)
  })
})

describe('fillCombobox (P2: the Workday ARIA-combobox driver)', () => {
  // jsdom can't run Workday's listbox JS, so we simulate the popup: clicking the
  // trigger appends a [role=listbox] with a search input + [role=option] rows.
  const withPopup = (triggerHtml: string, optionsHtml: string) => {
    document.body.innerHTML = triggerHtml
    const btn = document.body.firstElementChild as HTMLElement
    btn.addEventListener('click', () => {
      if (document.querySelector('[role=listbox]')) return
      const lb = document.createElement('div')
      lb.setAttribute('role', 'listbox')
      lb.innerHTML = `<input aria-label="Search" />${optionsHtml}`
      document.body.appendChild(lb)
    })
    return btn
  }

  test('opens, matches an option by text, and clicks it', async () => {
    const btn = withPopup(
      '<button aria-haspopup="listbox">Select One</button>',
      '<div role="option">Canada</div><div role="option">United States of America</div>',
    )
    let picked = ''
    document.addEventListener('click', (e) => {
      const t = e.target as HTMLElement
      if (t.getAttribute?.('role') === 'option') picked = t.textContent ?? ''
    })
    expect(await fillCombobox(btn, 'United States')).toBe(true)
    expect(picked).toBe('United States of America') // exact/unique match, never a blind first row
  })

  test('virtualized list: types into search to filter the match into the DOM, then picks it', async () => {
    // the live Workday symptom: the match option isn't rendered until the search
    // narrows the (huge, virtualized) list. Driver must type, wait, THEN pick.
    document.body.innerHTML = '<button aria-haspopup="listbox">Select One</button>'
    const btn = document.body.firstElementChild as HTMLElement
    let picked = ''
    btn.addEventListener('mousedown', () => {
      if (document.querySelector('[role=listbox]')) return
      const lb = document.createElement('div')
      lb.setAttribute('role', 'listbox')
      const search = document.createElement('input')
      lb.appendChild(search)
      const ALL = ['United States of America', 'United Kingdom', 'Uruguay']
      search.addEventListener('input', () => {
        lb.querySelectorAll('[role=option]').forEach((o) => o.remove())
        if (!search.value) return
        for (const t of ALL)
          if (t.toLowerCase().includes(search.value.toLowerCase())) {
            const o = document.createElement('div')
            o.setAttribute('role', 'option')
            o.textContent = t
            o.addEventListener('click', () => (picked = t))
            lb.appendChild(o)
          }
      })
      document.body.appendChild(lb) // opens EMPTY — the match only appears after typing
    })
    expect(await fillCombobox(btn, 'United States')).toBe(true)
    expect(picked).toBe('United States of America')
  })

  test('no match → false, nothing picked (never a blind first-row pick)', async () => {
    const btn = withPopup(
      '<button aria-haspopup="listbox">-</button>',
      '<div role="option">Canada</div><div role="option">Mexico</div>',
    )
    let picked = ''
    document.addEventListener('click', (e) => {
      const t = e.target as HTMLElement
      if (t.getAttribute?.('role') === 'option') picked = t.textContent ?? ''
    })
    expect(await fillCombobox(btn, 'Germany')).toBe(false)
    expect(picked).toBe('')
  })
})

describe('free-text answer guards (T13)', () => {
  test('alreadyFilled: never overwrite the user (and makes re-Fill idempotent)', () => {
    document.body.innerHTML = '<textarea id="a"></textarea><textarea id="b">mine</textarea>'
    expect(alreadyFilled(document.getElementById('a') as HTMLTextAreaElement)).toBe(false)
    expect(alreadyFilled(document.getElementById('b') as HTMLTextAreaElement)).toBe(true)
  })

  test('fitMaxLength: clamps to the field maxlength, passes through otherwise', () => {
    document.body.innerHTML = '<textarea id="t" maxlength="5"></textarea><textarea id="u"></textarea>'
    const capped = document.getElementById('t') as HTMLTextAreaElement
    const free = document.getElementById('u') as HTMLTextAreaElement
    expect(fitMaxLength(capped, 'abcdefgh')).toBe('abcde')
    expect(fitMaxLength(free, 'abcdefgh')).toBe('abcdefgh')
  })
})

describe('acceptsFreeText (Phase 1: a dropdown never receives a drafted sentence)', () => {
  const el = (html: string): Element => {
    document.body.innerHTML = html
    return document.body.firstElementChild!
  }

  test('plain text input and textarea accept free text', () => {
    expect(acceptsFreeText(el('<input type="text" />'))).toBe(true)
    expect(acceptsFreeText(el('<textarea></textarea>'))).toBe(true)
  })

  test('native <select> does NOT - a raw write sets selectedIndex -1 and blanks it', () => {
    expect(acceptsFreeText(el('<select><option>a</option></select>'))).toBe(false)
  })

  test('Workday-style button combobox does NOT', () => {
    expect(acceptsFreeText(el('<button aria-haspopup="listbox">Select One</button>'))).toBe(false)
  })

  test('REAL Greenhouse react-select School input does NOT (verbatim live markup)', () => {
    // Captured 2026-09-22 from job-boards.greenhouse.io/discord/jobs/8806163002.
    // It is an <input type=text>, so setNativeValue SUCCEEDS and leaves visible
    // prose - the exact reported bug. role=combobox is the only tell.
    const school = el(
      '<input class="select__input" id="school--0" type="text" aria-autocomplete="list" ' +
        'aria-haspopup="true" aria-labelledby="school--0-label" role="combobox" value="" />',
    )
    expect(school.tagName).toBe('INPUT') // not a <select> - the old select-only guard would miss it
    expect(acceptsFreeText(school)).toBe(false)
  })
})

describe('the real Greenhouse education fields are recognised as dropdowns', () => {
  test('School / Degree / Discipline all reject free text; the essay questions still accept it', async () => {
    const { loadFixture } = await import('./util')
    const { detectFields } = await import('../src/content/detector')
    loadFixture('greenhouse.html')
    const fields = detectFields(document)

    for (const id of ['school--0', 'degree--0', 'discipline--0']) {
      const f = fields.find((x) => x.descriptor.id === id)
      expect(f, `${id} must be detected`).toBeTruthy()
      expect(f!.descriptor.tag).toBe('combobox')
      expect(acceptsFreeText(f!.el), `${id} must reject free text`).toBe(false)
    }
    // regression guard: the genuine free-text question must STILL be writable,
    // or the fix would break ordinary screening answers.
    const why = fields.find((x) => x.descriptor.id === 'q_why')!
    expect(acceptsFreeText(why.el)).toBe(true)
  })
})

describe('reapplyValue (re-assert after an ATS re-render)', () => {
  test('a <select> is option-matched, never raw-written', () => {
    document.body.innerHTML =
      '<select id="s"><option value="">-</option><option value="ca">Canada</option></select>'
    const el = document.getElementById('s') as HTMLSelectElement
    reapplyValue(el, 'Canada') // the DISPLAY text, which is what the plan stores
    expect(el.value).toBe('ca')
    expect(el.selectedIndex).toBe(1)
  })

  test('an unmatched value leaves the <select> alone instead of blanking it', () => {
    // the regression: setNativeValue('Canada') on a select sets selectedIndex -1,
    // so re-asserting after a re-render would silently destroy the selection.
    document.body.innerHTML =
      '<select id="s"><option value="">-</option><option value="fr">France</option></select>'
    const el = document.getElementById('s') as HTMLSelectElement
    el.value = 'fr'
    reapplyValue(el, 'Germany')
    expect(el.value).toBe('fr') // untouched, not blanked
    expect(el.selectedIndex).not.toBe(-1)
  })

  test('inputs and textareas still take the plain write', () => {
    document.body.innerHTML = '<input id="i" /><textarea id="t"></textarea>'
    reapplyValue(document.getElementById('i') as HTMLInputElement, 'ada@analytical.io')
    reapplyValue(document.getElementById('t') as HTMLTextAreaElement, 'some prose')
    expect((document.getElementById('i') as HTMLInputElement).value).toBe('ada@analytical.io')
    expect((document.getElementById('t') as HTMLTextAreaElement).value).toBe('some prose')
  })
})
