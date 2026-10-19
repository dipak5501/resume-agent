import { defineConfig } from 'vitest/config'

// Pure unit tests (detector/mapper/plan) run in jsdom — no CRXJS plugin, so the
// extension build machinery stays out of the test run.
export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.ts'],
  },
})
