import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import type { Descriptor } from '../src/shared/types'

const here = dirname(fileURLToPath(import.meta.url))

/** Load a saved ATS form fixture into the jsdom document body. */
export function loadFixture(name: string): void {
  document.body.innerHTML = readFileSync(join(here, 'fixtures', name), 'utf8')
}

/** A Descriptor with every field defaulted; override just what a test needs. */
export function bare(over: Partial<Descriptor> = {}): Descriptor {
  return {
    field_ref: 0, tag: 'input', type: 'text', name: '', id: '', autocomplete: '',
    aria_label: '', placeholder: '', label: '', data_automation_id: '', required: false, ...over,
  }
}
