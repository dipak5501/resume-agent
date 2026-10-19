import { readdirSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, test } from 'vitest'

// The Fill path never submits. auto-apply.ts may call requestSubmit, and only
// after canAutoSubmit returns ok. .click( and form.submit( stay forbidden.
const contentDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'content')

const FORBIDDEN = [/\.submit\s*\(/, /requestSubmit/, /\.click\s*\(/]
const GATED = 'auto-apply.ts'

describe('no auto-submit', () => {
  const files = readdirSync(contentDir).filter((f) => f.endsWith('.ts'))

  test('there is at least one content-script file to scan', () => {
    expect(files.length).toBeGreaterThan(0)
  })

  for (const file of files) {
    if (file === GATED) {
      test('auto-apply submits only behind the gate', () => {
        const src = readFileSync(join(contentDir, file), 'utf8')
        expect(src).toContain('canAutoSubmit')
        expect(src).toMatch(/if \(!gate\.ok\) return gate[\s\S]*requestSubmit/)
        expect(src).not.toMatch(/\.click\s*\(/)
        expect(src).not.toMatch(/\.submit\s*\(/)
      })
      continue
    }
    test(`${file} contains no submit/click code path`, () => {
      const src = readFileSync(join(contentDir, file), 'utf8')
      for (const pattern of FORBIDDEN) {
        expect(pattern.test(src), `${file} must not match ${pattern}`).toBe(false)
      }
    })
  }
})
