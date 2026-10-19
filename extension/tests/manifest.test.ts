import { describe, expect, test } from 'vitest'

import rawManifest from '../src/manifest'

// defineManifest's export type is a union (object | fn | promise); ours is a
// plain object. Narrow structurally for the fields this test reads.
const manifest = rawManifest as {
  background?: { service_worker?: string }
  content_scripts?: { js?: string[] }[]
}

// CRXJS/Rollup key emitted chunks by file BASENAME. Two entry files sharing a
// basename (e.g. background/index.ts + content/index.ts) collide — one bundle
// silently overwrites the other, and the service worker ends up running the
// content script (breaks all popup↔worker messaging with "message port closed").
// This guards that root cause without needing a full build.
describe('manifest entry files have distinct basenames', () => {
  const basename = (p: string) => p.split('/').pop()!

  test('background worker basename differs from every content script', () => {
    const sw = basename(manifest.background!.service_worker!)
    const contentEntries = (manifest.content_scripts ?? []).flatMap((cs) => cs.js ?? []).map(basename)
    expect(contentEntries).not.toContain(sw)
    expect(sw).not.toBe('index.ts') // the specific footgun: a second index.ts entry
  })
})
