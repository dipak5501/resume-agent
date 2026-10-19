import { describe, expect, test } from 'vitest'

import { mapDescriptor } from '../src/content/mapper'
import type { Canonical, Descriptor } from '../src/shared/types'
import fixtures from './fixtures/mapper-parity.json'
import { bare } from './util'

// Cross-language mapper parity (T18). This SAME fixture file is read by the
// backend test (backend/tests/test_mapper_parity.py). Both run their own mapper
// over it and assert the SAME expected canonical — so if mapper.ts and
// field_map.py ever drift, one side goes red. The extension is the canonical
// source of truth; the backend mirrors it. Drift is a red test, not a wrong
// value on a submitted application.
describe('mapper parity (shared fixtures)', () => {
  for (const { note, expected, descriptor } of fixtures) {
    test(`${note} → ${expected}`, () => {
      expect(mapDescriptor(bare(descriptor as Partial<Descriptor>)).canonical).toBe(expected as Canonical)
    })
  }
})
