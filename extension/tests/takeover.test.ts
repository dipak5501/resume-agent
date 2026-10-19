import { afterEach, describe, expect, test, vi } from 'vitest'

import { fillCombobox, listboxSnapshot, optionsIn, popupFor } from '../src/content/apply'
import {
  noteUserActivity,
  preservingFocus,
  preservingPageScroll,
  resetTakeoverForTest,
  userHasTakenOver,
  userTouched,
  watchTakeover,
} from '../src/content/takeover'

afterEach(() => resetTakeoverForTest())

// jsdom defines `isTrusted` as an own NON-CONFIGURABLE getter, so a trusted event
// cannot be forged. We therefore exercise a real user action through the same
// entry point the listener uses, and prove the isTrusted guard separately below
// with genuinely dispatched events (which is the half that can actually go wrong:
// our own driver events must never be mistaken for the user).
function userActs(el: Element): void {
  noteUserActivity(el)
}

describe('takeover: the user outranks the autofill', () => {
  test('a REAL keystroke stands the fill down', () => {
    document.body.innerHTML = '<input id="a" />'
    watchTakeover()
    expect(userHasTakenOver()).toBe(false)
    userActs(document.getElementById('a')!)
    expect(userHasTakenOver()).toBe(true)
  })

  test('OUR OWN dispatched events never count - this is the whole trick', () => {
    // fillCombobox dispatches mousedown/mouseup/click and an Escape keydown. If
    // those counted, the driver would stand down against itself on field one and
    // nothing would ever be filled.
    document.body.innerHTML = '<button id="b" aria-haspopup="listbox"></button>'
    watchTakeover()
    const el = document.getElementById('b')!
    el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
    el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
    expect(userHasTakenOver()).toBe(false)
  })

  test('listens for pointerdown/keydown/wheel/touchstart on the document', () => {
    // wheel matters: moving the viewport under a user who is scrolling IS the bug.
    const spy = vi.spyOn(document, 'addEventListener')
    watchTakeover()
    const types = spy.mock.calls.map((c) => c[0])
    for (const t of ['pointerdown', 'keydown', 'wheel', 'touchstart']) {
      expect(types, `must listen for ${t}`).toContain(t)
    }
    spy.mockRestore()
  })

  test('userTouched remembers WHICH control the user worked on', () => {
    document.body.innerHTML = '<input id="a" /><input id="b" />'
    watchTakeover()
    const a = document.getElementById('a')!
    const b = document.getElementById('b')!
    userActs(a)
    expect(userTouched(a)).toBe(true)
    expect(userTouched(b)).toBe(false)
    expect(userTouched(null)).toBe(false)
  })

  test('a touched field survives an ATS re-render (node swap)', () => {
    // `liveElement` re-finds fields by id/name precisely so an Ashby-style
    // re-render is still reachable. Keying "touched" on the node alone meant the
    // swapped-in node looked untouched and reassertFills wrote the wrong value
    // back into the field the user had just cleared.
    document.body.innerHTML = '<input id="x" name="x" value="wrong" />'
    const oldNode = document.getElementById('x')!
    watchTakeover()
    userActs(oldNode)
    document.body.innerHTML = '<input id="x" name="x" value="" />' // re-render
    const newNode = document.getElementById('x')!
    expect(newNode).not.toBe(oldNode)
    expect(userTouched(newNode)).toBe(true)
  })

  test('identity matching does not leak to an unrelated field', () => {
    document.body.innerHTML = '<input id="a" /><input id="b" /><input />'
    watchTakeover()
    userActs(document.getElementById('a')!)
    expect(userTouched(document.getElementById('b')!)).toBe(false)
    // a field with neither id nor name has no stable key - must not match blindly
    expect(userTouched(document.querySelectorAll('input')[2])).toBe(false)
  })

  test('a mouse-only dropdown pick is credited to the dropdown, not the <svg>/<div> it lands on', () => {
    // Measured live on Greenhouse react-select: the two pointerdowns of a pick hit
    // the arrow's <svg path> and the option <div>, never the <input>.
    document.body.innerHTML = `
      <div class="field"><label for="h">Hispanic/Latino?</label>
        <div class="select__control"><input id="h" role="combobox" /><svg><path id="arrow"/></svg></div>
        <input type="hidden" name="h" value="" />
        <div role="listbox"><div role="option" id="opt">Decline</div></div>
      </div>
      <div class="field"><input id="other" /></div>`
    watchTakeover()
    userActs(document.getElementById('opt')!) // the option alone (the menu sits beside the hidden input)
    expect(userTouched(document.getElementById('h'))).toBe(true)
    resetTakeoverForTest()
    watchTakeover()
    userActs(document.getElementById('arrow')!)
    expect(userTouched(document.getElementById('h'))).toBe(true)
    expect(userTouched(document.getElementById('other'))).toBe(false)
  })

  test('a click in a block holding several fields credits none of them', () => {
    document.body.innerHTML = '<form><p id="p">Personal info</p><input id="a" /><input id="b" /></form>'
    watchTakeover()
    userActs(document.getElementById('p')!)
    expect(userTouched(document.getElementById('a'))).toBe(false)
    expect(userTouched(document.getElementById('b'))).toBe(false)
    expect(userHasTakenOver()).toBe(true) // still stands the fill down
  })

  test('scrolling over a field stands the fill down but does not claim the field', () => {
    // Claiming it would stop reassertFills restoring a value an ATS re-render blanked.
    document.body.innerHTML = '<div class="field"><label id="l" for="a">Email</label><input id="a" /></div>'
    const spy = vi.spyOn(document, 'addEventListener')
    watchTakeover()
    const listener = spy.mock.calls.find((c) => c[0] === 'wheel')![1] as (e: unknown) => void
    spy.mockRestore()
    listener({ isTrusted: true, type: 'wheel', target: document.getElementById('a') })
    expect(userHasTakenOver()).toBe(true)
    expect(userTouched(document.getElementById('a'))).toBe(false)
    listener({ isTrusted: true, type: 'pointerdown', target: document.getElementById('l') })
    expect(userTouched(document.getElementById('a'))).toBe(true) // a click on its label does
  })

  test('watchTakeover is idempotent and resets the flag for a new fill', () => {
    document.body.innerHTML = '<input id="a" />'
    watchTakeover()
    userActs(document.getElementById('a')!)
    expect(userHasTakenOver()).toBe(true)
    watchTakeover() // a second Fill starts
    expect(userHasTakenOver()).toBe(false)
  })
})

describe('preservingPageScroll / preservingFocus', () => {
  test('puts the page back when the body moved the viewport', () => {
    const scrollTo = vi.fn()
    let x = 0
    let y = 0
    vi.spyOn(window, 'scrollX', 'get').mockImplementation(() => x)
    vi.spyOn(window, 'scrollY', 'get').mockImplementation(() => y)
    vi.stubGlobal('scrollTo', scrollTo)
    preservingPageScroll(() => {
      y = 900 // what scrollIntoView does to the document
    })
    expect(scrollTo).toHaveBeenCalledWith(0, 0)
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    void x
  })

  test('does NOT call scrollTo when nothing moved (no pointless jitter)', () => {
    const scrollTo = vi.fn()
    vi.stubGlobal('scrollTo', scrollTo)
    preservingPageScroll(() => undefined)
    expect(scrollTo).not.toHaveBeenCalled()
    vi.unstubAllGlobals()
  })

  test('restores the caret the driver stole', () => {
    document.body.innerHTML = '<input id="mine" /><input id="popup" />'
    const mine = document.getElementById('mine') as HTMLInputElement
    const popup = document.getElementById('popup') as HTMLInputElement
    mine.focus()
    expect(document.activeElement).toBe(mine)
    preservingFocus(() => popup.focus())
    expect(document.activeElement).toBe(mine) // the user keeps typing where they were
  })
})

describe('popupFor: never another control\'s listbox', () => {
  test('aria-controls wins (react-select publishes it when open)', () => {
    document.body.innerHTML =
      '<div role="listbox" id="iti-0__country-listbox"><div role="option">Afghanistan+93</div></div>' +
      '<input id="degree--0" role="combobox" aria-controls="react-select-degree--0-listbox" />' +
      '<div role="listbox" id="react-select-degree--0-listbox"><div role="option">Bachelor\'s Degree</div></div>'
    const trigger = document.getElementById('degree--0')!
    const popup = popupFor(trigger, listboxSnapshot())
    expect(popup?.id).toBe('react-select-degree--0-listbox')
    expect(optionsIn(popup).map((o) => o.textContent)).toEqual(["Bachelor's Degree"])
  })

  test('an ALWAYS-MOUNTED listbox is never adopted (the live Greenhouse hazard)', () => {
    // Verified live: Greenhouse keeps the phone widget's 244-option country
    // listbox in the DOM at all times, FIRST in document order. The old global
    // querySelector returned it for every control on the page.
    document.body.innerHTML =
      '<div role="listbox" id="iti-0__country-listbox"><div role="option">Afghanistan+93</div></div>' +
      '<input id="school--0" role="combobox" />'
    const before = listboxSnapshot() // country list already mounted
    const popup = popupFor(document.getElementById('school--0')!, before)
    expect(popup).toBe(null) // no popup of our own -> caller blanks + flags
  })

  test('a popup that APPEARS after opening is adopted (the Workday portal shape)', () => {
    document.body.innerHTML = '<button id="t" aria-haspopup="listbox"></button>'
    const before = listboxSnapshot()
    const lb = document.createElement('div')
    lb.setAttribute('role', 'listbox')
    lb.id = 'fresh'
    document.body.appendChild(lb)
    expect(popupFor(document.getElementById('t')!, before)?.id).toBe('fresh')
  })

  test('two new popups is ambiguous -> take neither', () => {
    document.body.innerHTML = '<button id="t" aria-haspopup="listbox"></button>'
    const before = listboxSnapshot()
    for (const id of ['x', 'y']) {
      const lb = document.createElement('div')
      lb.setAttribute('role', 'listbox')
      lb.id = id
      document.body.appendChild(lb)
    }
    expect(popupFor(document.getElementById('t')!, before)).toBe(null)
  })
})

describe('fillCombobox stands down and stays scoped', () => {
  test('refuses to open a popup once the user is typing', async () => {
    document.body.innerHTML = '<button id="t" aria-haspopup="listbox"></button><input id="u" />'
    watchTakeover()
    userActs(document.getElementById('u')!)
    let opened = false
    document.getElementById('t')!.addEventListener('mousedown', () => (opened = true))
    expect(await fillCombobox(document.getElementById('t') as HTMLElement, 'Canada')).toBe(false)
    expect(opened).toBe(false) // never opened a dropdown over the user
  })

  test('does NOT match against a decoy always-mounted country list', async () => {
    // Before the fix, 'Canada' would have matched the country listbox's option
    // and been clicked - selecting a phone country code nobody asked for.
    document.body.innerHTML =
      '<div role="listbox" id="iti-0__country-listbox"><div role="option">Canada+1</div></div>' +
      '<button id="t" aria-haspopup="listbox"></button>'
    watchTakeover()
    let picked = ''
    document.querySelector('#iti-0__country-listbox [role=option]')!.addEventListener('click', function (this: HTMLElement) {
      picked = this.textContent ?? ''
    })
    // the trigger opens nothing (simulating a widget whose list never renders)
    expect(await fillCombobox(document.getElementById('t') as HTMLElement, 'Canada')).toBe(false)
    expect(picked).toBe('') // the decoy was never touched
  })
})


describe('react-select shape: the trigger IS the search box', () => {
  // Greenhouse has no separate popup search input, so typing to filter writes
  // into the VISIBLE control. Caught in a self-audit: the typeahead left our
  // search string sitting in the School box after a failed match - the reported
  // bug in another costume.
  const greenhouseCombobox = (optionsHtml: string) => {
    document.body.innerHTML =
      `<div class="field"><input id="school--0" role="combobox" aria-haspopup="true" value="" /></div>`
    const trigger = document.getElementById('school--0') as HTMLInputElement
    trigger.addEventListener('mousedown', () => {
      if (document.querySelector('[role=listbox]')) return
      const lb = document.createElement('div')
      lb.setAttribute('role', 'listbox')
      lb.innerHTML = optionsHtml
      trigger.closest('.field')!.appendChild(lb)
    })
    resetTakeoverForTest()
    watchTakeover()
    return trigger
  }

  test('a failed match leaves the control exactly as it found it', async () => {
    const trigger = greenhouseCombobox('<div role="option">Harvard University</div>')
    expect(await fillCombobox(trigger, 'California State University, Long Beach')).toBe(false)
    expect(trigger.value).toBe('')
  })

  test('a pre-existing value is put back, not clobbered', async () => {
    const trigger = greenhouseCombobox('<div role="option">Harvard University</div>')
    trigger.value = 'Stanford'
    expect(await fillCombobox(trigger, 'Nowhere University')).toBe(false)
    expect(trigger.value).toBe('Stanford')
  })

  test('a successful match still picks the option', async () => {
    const trigger = greenhouseCombobox('<div role="option">Harvard University</div>')
    let picked = ''
    document.addEventListener('click', (e) => {
      const t = e.target as HTMLElement
      if (t.getAttribute?.('role') === 'option') picked = t.textContent ?? ''
    })
    expect(await fillCombobox(trigger, 'Harvard University')).toBe(true)
    expect(picked).toBe('Harvard University')
  })

  test('focus is NOT handed back to a non-form element (react-select closes on blur)', () => {
    // jsdom will not focus <body>, so asserting on activeElement proves nothing
    // here - spy on the restore itself. Restoring to body/div mid-drive would
    // blur the combobox and the option would never become pickable.
    document.body.innerHTML = '<div id="d" tabindex="-1"></div><input id="c" />'
    const d = document.getElementById('d') as HTMLElement
    d.focus()
    const spy = vi.spyOn(d, 'focus')
    preservingFocus(() => (document.getElementById('c') as HTMLInputElement).focus())
    expect(spy).not.toHaveBeenCalled()
    spy.mockRestore()
  })

  test('...but a real caret IS handed back (the user was typing)', () => {
    document.body.innerHTML = '<input id="mine" /><input id="popup" />'
    const mine = document.getElementById('mine') as HTMLInputElement
    mine.focus()
    const spy = vi.spyOn(mine, 'focus')
    preservingFocus(() => (document.getElementById('popup') as HTMLInputElement).focus())
    expect(spy).toHaveBeenCalledWith({ preventScroll: true })
    spy.mockRestore()
  })
})

describe('fillCombobox confirms the pick actually committed', () => {
  const widget = (opts: string, commits: boolean) => {
    document.body.innerHTML =
      '<div class="field"><input id="c" role="combobox" aria-haspopup="true" aria-expanded="false" value="" /></div>'
    const trigger = document.getElementById('c') as HTMLInputElement
    trigger.addEventListener('mousedown', () => {
      if (document.querySelector('[role=listbox]')) return
      trigger.setAttribute('aria-expanded', 'true')
      const lb = document.createElement('div')
      lb.setAttribute('role', 'listbox')
      lb.innerHTML = opts
      trigger.closest('.field')!.appendChild(lb)
      // a committing widget collapses when an option is clicked
      if (commits) {
        lb.addEventListener('click', () => trigger.setAttribute('aria-expanded', 'false'))
      }
    })
    resetTakeoverForTest()
    watchTakeover()
    return trigger
  }

  test('a widget that commits reports success', async () => {
    const t = widget('<div role="option">Canada</div>', true)
    expect(await fillCombobox(t, 'Canada')).toBe(true)
  })

  test('a click that silently does nothing is reported as FAILED, not filled', async () => {
    // measured live: a committed react-select pick sets aria-expanded="false".
    // Still open means nothing was selected - reporting "filled" there would put
    // a fill in the review list that does not exist on the page.
    const t = widget('<div role="option">Canada</div>', false)
    expect(await fillCombobox(t, 'Canada')).toBe(false)
    expect(t.value).toBe('') // and our typeahead text is cleaned up
  })
})
