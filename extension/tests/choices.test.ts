import { beforeEach, describe, expect, it } from 'vitest'

import { detectRadioGroups } from '../src/content/choices'

beforeEach(() => {
  document.body.innerHTML = ''
})

describe('detectRadioGroups', () => {
  it('groups radios by name and resolves the question + options', () => {
    document.body.innerHTML = `
      <div class="application-question">
        <div class="application-label">Are you legally eligible to work in the US?</div>
        <ul>
          <li><label><input type="radio" name="q1" value="Yes" required /> Yes</label></li>
          <li><label><input type="radio" name="q1" value="No" /> No</label></li>
        </ul>
      </div>`
    const groups = detectRadioGroups(document, 5)
    expect(groups).toHaveLength(1)
    expect(groups[0].field_ref).toBe(5) // continues after the text fields
    expect(groups[0].question.toLowerCase()).toContain('eligible to work')
    expect(groups[0].options.map((o) => o.label)).toEqual(['Yes', 'No'])
    expect(groups[0].required).toBe(true)
  })

  it('gives each group a distinct field_ref and ignores a lone radio', () => {
    document.body.innerHTML = `
      <fieldset><legend>Q1</legend>
        <label><input type="radio" name="a" value="Yes"/> Yes</label>
        <label><input type="radio" name="a" value="No"/> No</label>
      </fieldset>
      <fieldset><legend>Q2</legend>
        <label><input type="radio" name="b" value="Yes"/> Yes</label>
        <label><input type="radio" name="b" value="No"/> No</label>
      </fieldset>
      <label><input type="radio" name="lonely" value="x"/> single</label>`
    const groups = detectRadioGroups(document, 0)
    expect(groups.map((g) => g.name)).toEqual(['a', 'b']) // lone radio dropped
    expect(groups.map((g) => g.field_ref)).toEqual([0, 1])
  })
})
