// The popup's review summary, rendered in jsdom from a restored fill result.
import { act, createElement } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, test, vi } from 'vitest'

import { App } from '../src/popup/App'
import { YOURS } from '../src/shared/mark-kind'
import type { FillResult, PlanItem } from '../src/shared/types'

;(globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean }).IS_REACT_ACT_ENVIRONMENT = true

const flag = (field_ref: number, reason: string): PlanItem => ({ field_ref, label: `f${field_ref}`, canonical: 'unknown', action: 'flag', reason })

/** Open the popup on a tab whose last fill produced `result`. */
async function openPopup(result: FillResult): Promise<string> {
  vi.stubGlobal('chrome', {
    runtime: { lastError: undefined, sendMessage: (_m: unknown, reply: (r: unknown) => void) => reply([]) },
    tabs: {
      query: (_q: unknown, cb: (tabs: { id: number }[]) => void) => cb([{ id: 1 }]),
      sendMessage: (_id: number, _m: unknown, cb: (r: unknown) => void) => cb({ formPresent: true }),
    },
    storage: { session: { get: (key: string, cb: (o: object) => void) => cb({ [key]: result }) } },
  })
  const root = document.createElement('div')
  await act(async () => createRoot(root).render(createElement(App)))
  return root.textContent ?? ''
}

afterEach(() => vi.unstubAllGlobals())

describe('popup review', () => {
  test("a field the user answered is never counted as one we couldn't map", async () => {
    const empty = { filled: [], attached: [], blank: [] }
    const mixed = await openPopup({ ...empty, flagged: [flag(0, YOURS), flag(1, 'no idea what this is')] })
    expect(mixed).toContain('+ 1 field we couldn’t map')

    const allYours = await openPopup({ ...empty, flagged: [flag(0, YOURS), flag(1, YOURS)] })
    expect(allYours).not.toContain('couldn’t map')
    expect(allYours).toContain('All clear')
  })
})
