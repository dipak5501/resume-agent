// Radio-group detection (T17). A screening question like "Are you legally
// eligible to work in the US? (Yes/No)" is ONE logical field with options — not
// two — so we group radios by `name` and resolve the question text + the option
// labels. Pure DOM read (no chrome APIs) so it unit-tests in jsdom.

import { clean, labelByFor } from './dom'

export interface ChoiceOption {
  label: string
  value: string
  el: HTMLInputElement
}

export interface ChoiceGroup {
  field_ref: number
  name: string
  question: string
  required: boolean
  options: ChoiceOption[]
  container: HTMLElement // anchor for the on-page proof mark
}

/** The text label for one radio option (the "Yes"/"No" bit). */
function optionLabel(el: HTMLInputElement): string {
  const forLabel = labelByFor(el)
  if (forLabel) return forLabel
  const wrap = el.closest('label')
  if (wrap?.textContent) return clean(wrap.textContent)
  const aria = el.getAttribute('aria-label')
  if (aria) return clean(aria)
  // the visible text usually sits in the next sibling of the input (or its wrapper)
  const sib = (el.parentElement?.nextElementSibling ?? el.nextElementSibling)?.textContent
  if (sib && clean(sib)) return clean(sib)
  return clean(el.value)
}

const QUESTION_WRAPPER = 'fieldset,[role="radiogroup"],.application-question,.field,.form-group,li,section'

/** The question block for the group: the nearest semantic wrapper that contains
 *  every radio (so the question label — often a sibling of the options list, not
 *  an ancestor of the radios — is included), else the smallest common ancestor. */
function groupContainer(radios: HTMLInputElement[]): HTMLElement {
  const body = radios[0].ownerDocument.body
  let common: HTMLElement | null = null
  let node: HTMLElement | null = radios[0].parentElement
  while (node && node !== body) {
    if (radios.every((r) => node!.contains(r))) {
      common = common ?? node
      if (node.matches(QUESTION_WRAPPER)) return node // prefer a real question wrapper
    }
    node = node.parentElement
  }
  return common ?? radios[0].parentElement ?? radios[0]
}

/** The question text = the container's text with the option labels removed. */
function groupQuestion(radios: HTMLInputElement[], container: HTMLElement): string {
  const labelled = container.querySelector('legend, .application-label, label:not([for])')
  const optionText = new Set(radios.map((r) => optionLabel(r).toLowerCase()))
  const strip = (t: string) =>
    clean(
      t
        .split(/\s{2,}|\n/)
        .filter((chunk) => !optionText.has(clean(chunk).toLowerCase()))
        .join(' '),
    )
  if (labelled?.textContent) {
    const q = strip(labelled.textContent)
    if (q) return q.slice(0, 200)
  }
  return strip(container.textContent || '').slice(0, 200)
}

function isDetectable(el: HTMLInputElement): boolean {
  if (el.closest('[aria-hidden="true"]')) return false
  const cs = el.ownerDocument.defaultView?.getComputedStyle(el)
  // styled radios are commonly opacity:0 behind a custom circle — keep those;
  // only a display:none control is truly absent.
  return !cs || cs.display !== 'none'
}

/** Detect Yes/No/choice radio groups. `startRef` continues the field_ref series
 *  after the text fields so ids stay unique across the whole plan. */
export function detectRadioGroups(root: Document | Element = document, startRef = 0): ChoiceGroup[] {
  const byName = new Map<string, HTMLInputElement[]>()
  for (const el of root.querySelectorAll<HTMLInputElement>('input[type=radio]')) {
    if (!el.name || !isDetectable(el)) continue
    const list = byName.get(el.name) ?? []
    list.push(el)
    byName.set(el.name, list)
  }
  const groups: ChoiceGroup[] = []
  let ref = startRef
  for (const [name, radios] of byName) {
    if (radios.length < 2) continue // a lone radio isn't a choice group
    const container = groupContainer(radios)
    groups.push({
      field_ref: ref++,
      name,
      question: groupQuestion(radios, container),
      required: radios.some((r) => r.required || r.getAttribute('aria-required') === 'true'),
      options: radios.map((el) => ({ label: optionLabel(el), value: el.value || optionLabel(el), el })),
      container,
    })
  }
  return groups
}
