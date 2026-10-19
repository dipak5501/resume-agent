import { afterEach, describe, expect, test } from 'vitest'

import { sendToBackground } from '../src/shared/messaging'

type Cb = (resp: unknown) => void
function stubChrome(handler: (msg: unknown, cb: Cb) => void) {
  const runtime = { lastError: undefined as { message: string } | undefined }
  ;(globalThis as unknown as { chrome: unknown }).chrome = {
    runtime: {
      get lastError() {
        return runtime.lastError
      },
      set lastError(v) {
        runtime.lastError = v
      },
      sendMessage: (msg: unknown, cb: Cb) => handler(msg, cb),
    },
  }
  return runtime
}

afterEach(() => {
  delete (globalThis as unknown as { chrome?: unknown }).chrome
})

describe('sendToBackground (MV3 cold-worker resilience)', () => {
  test('retries after a dropped wake-up message, then resolves', async () => {
    let calls = 0
    const rt = stubChrome((_msg, cb) => {
      calls++
      if (calls === 1) {
        rt.lastError = { message: 'The message port closed before a response was received.' }
        cb(undefined)
      } else {
        rt.lastError = undefined
        cb({ ok: true })
      }
    })
    await expect(sendToBackground({ type: 'LIST_JOBS' }, { retries: 3, backoffMs: 1 })).resolves.toEqual({
      ok: true,
    })
    expect(calls).toBe(2)
  })

  test('does NOT retry a real application error — surfaces it immediately', async () => {
    let calls = 0
    const rt = stubChrome((_msg, cb) => {
      calls++
      rt.lastError = undefined
      cb({ error: 'backend 500' })
    })
    await expect(sendToBackground({ type: 'X' }, { retries: 3, backoffMs: 1 })).rejects.toThrow('backend 500')
    expect(calls).toBe(1)
  })

  test('gives up after exhausting retries on a persistent drop', async () => {
    let calls = 0
    const rt = stubChrome((_msg, cb) => {
      calls++
      rt.lastError = { message: 'Could not establish connection. Receiving end does not exist.' }
      cb(undefined)
    })
    await expect(sendToBackground({ type: 'X' }, { retries: 2, backoffMs: 1 })).rejects.toThrow(/Receiving end/)
    expect(calls).toBe(3) // initial + 2 retries
  })
})
