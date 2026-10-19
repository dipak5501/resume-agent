// Resilient wrapper over chrome.runtime.sendMessage (T12).
//
// MV3 service workers are ephemeral module workers — Chrome terminates them when
// idle and wakes them on the next event. The very first message to a COLD worker
// can lose the response, surfacing as "The message port closed before a response
// was received" or "Could not establish connection. Receiving end does not
// exist." These are transient wake-up races: resend and the (now-warm) worker
// answers. Real application errors (resp.error) are NOT retried — they surface
// at once. Shared by popup and content script (they hit the same worker).

const TRANSIENT = /message port closed|Receiving end does not exist|Could not establish connection/i

export interface SendOpts {
  retries?: number
  backoffMs?: number
}

export function sendToBackground<T>(msg: unknown, opts: SendOpts = {}): Promise<T> {
  const retries = opts.retries ?? 3
  const backoffMs = opts.backoffMs ?? 120
  const attempt = (left: number): Promise<T> =>
    new Promise<T>((resolve, reject) => {
      chrome.runtime.sendMessage(msg, (resp) => {
        const err = chrome.runtime.lastError
        if (err) {
          if (left > 0 && TRANSIENT.test(err.message ?? '')) {
            setTimeout(() => attempt(left - 1).then(resolve, reject), backoffMs)
            return
          }
          return reject(new Error(err.message))
        }
        if (resp && (resp as { error?: string }).error) return reject(new Error((resp as { error: string }).error))
        resolve(resp as T)
      })
    })
  return attempt(retries)
}
