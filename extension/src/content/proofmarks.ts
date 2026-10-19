// On-page "proof marks" (T15) — the signature surface. We mark the ATS form the
// way a proofreader marks a manuscript: each touched field gets a margin mark by
// category, and AI drafts are editable in place. Everything lives in a Shadow
// DOM so the host page's CSS can't collide with ours (or vice-versa), the layer
// never blocks the form's inputs, and it's torn down on navigation/submit.
//
// Presentation only: it reads the plan T12/T13 already produced and restyles it.
import { markKind, type MarkKind as Kind } from '../shared/mark-kind'
import tokensCss from '../shared/tokens.css?inline'
import type { PlanItem } from '../shared/types'
import { setNativeValue } from './apply'
import type { DetectedField } from './detector'

type Editable = HTMLInputElement | HTMLTextAreaElement

interface Entry {
  ref: number
  el: HTMLElement
  ring: HTMLElement
  chip: HTMLElement
  kind: Kind
  item: PlanItem
}

const HOST_ID = 'resume-agent-proof-layer'
let host: HTMLElement | null = null
let root: ShadowRoot | null = null
let layer: HTMLElement | null = null
let entries: Entry[] = []
let editor: HTMLElement | null = null
let rafPending = false

const GLYPH: Record<Kind, string> = {
  draft: '✎',
  choice: '☑',
  ok: '✓',
  blank: '‸',
  sensitive: '⊘',
  query: '?',
  flag: '!',
}
const TAG: Record<Kind, string> = {
  draft: 'draft · review',
  choice: 'answered · review',
  ok: '',
  blank: 'needs you',
  sensitive: 'left for you',
  query: 'check this',
  flag: 'for you',
}

/** Mark the form for a freshly-applied plan. Idempotent — clears any prior run. */
export function renderProofMarks(fields: DetectedField[], plan: PlanItem[]): void {
  clearProofMarks()
  host = document.createElement('div')
  host.id = HOST_ID
  root = host.attachShadow({ mode: 'open' })
  const style = document.createElement('style')
  style.textContent = tokensCss + LAYER_CSS
  root.appendChild(style)
  layer = document.createElement('div')
  layer.className = 'layer'
  root.appendChild(layer)
  document.body.appendChild(host)

  const byRef = new Map(fields.map((f) => [f.descriptor.field_ref, f.el]))
  for (const item of plan) {
    if (item.action === 'answer') continue // an unresolved placeholder — skip
    const el = byRef.get(item.field_ref)
    if (!el) continue
    const kind = markKind(item)
    // Don't clutter the page with a mark on every field we simply couldn't map —
    // those are surfaced as a single count in the popup instead. Only the marks
    // that need real attention stay on the page.
    if (kind === 'flag') continue
    const ring = document.createElement('div')
    ring.className = `ring k-${kind}`
    const chip = buildChip(kind, item, el)
    layer.append(ring, chip)
    entries.push({ ref: item.field_ref, el, ring, chip, kind, item })
  }
  position()
  window.addEventListener('scroll', schedule, true)
  window.addEventListener('resize', schedule)
  window.addEventListener('pagehide', clearProofMarks, { once: true })
  document.addEventListener('submit', clearProofMarks, true)
}

function buildChip(kind: Kind, item: PlanItem, el: HTMLElement): HTMLElement {
  const chip = document.createElement(kind === 'draft' ? 'button' : 'div')
  chip.className = `chip k-${kind}`
  chip.setAttribute('data-ref', String(item.field_ref))
  const glyph = document.createElement('span')
  glyph.className = 'glyph'
  glyph.textContent = GLYPH[kind]
  chip.appendChild(glyph)
  if (TAG[kind]) {
    const tag = document.createElement('span')
    tag.className = 'tag'
    tag.textContent = TAG[kind]
    chip.appendChild(tag)
  }
  if (kind === 'draft') {
    ;(chip as HTMLButtonElement).type = 'button'
    chip.setAttribute('aria-label', `Edit AI draft for ${item.label}`)
    chip.addEventListener('click', () => openEditor(el as Editable, item))
  }
  return chip
}

/** Reposition every mark to its field's current viewport box. */
function position(): void {
  for (const e of entries) {
    const r = e.el.getBoundingClientRect()
    // ring hugs the field
    Object.assign(e.ring.style, {
      top: `${r.top - 2}px`,
      left: `${r.left - 2}px`,
      width: `${r.width + 4}px`,
      height: `${r.height + 4}px`,
    })
    // chip sits in the field's left margin, or to the right if there's no room
    const cw = e.chip.offsetWidth || 90
    const ch = e.chip.offsetHeight || 20
    const left = r.left - cw - 8
    e.chip.style.top = `${Math.max(2, r.top + r.height / 2 - ch / 2)}px`
    e.chip.style.left = left > 4 ? `${left}px` : `${r.right + 8}px`
  }
  if (editor) positionEditor()
}

function schedule(): void {
  if (rafPending) return
  rafPending = true
  requestAnimationFrame(() => {
    rafPending = false
    position()
  })
}

/** Popup → content: scroll a flagged field into view, focus it, pulse its mark. */
export function focusField(ref: number): void {
  const e = entries.find((x) => x.ref === ref)
  if (!e) return
  e.el.scrollIntoView({ behavior: 'smooth', block: 'center' })
  ;(e.el as Partial<HTMLInputElement>).focus?.({ preventScroll: true })
  schedule()
  e.ring.classList.remove('pulse')
  void e.ring.offsetWidth // restart the animation
  e.ring.classList.add('pulse')
}

// --- inline edit of an AI draft, in the Shadow layer -------------------------

let editTarget: { el: Editable } | null = null

function openEditor(el: Editable, item: PlanItem): void {
  closeEditor()
  editTarget = { el }
  editor = document.createElement('div')
  editor.className = 'editor'
  const head = document.createElement('div')
  head.className = 'ed-head'
  head.textContent = item.label
  const ta = document.createElement('textarea')
  ta.className = 'ed-text'
  ta.value = el.value
  ta.setAttribute('aria-label', `AI draft for ${item.label}`)
  const row = document.createElement('div')
  row.className = 'ed-row'
  const save = document.createElement('button')
  save.type = 'button'
  save.className = 'ed-save'
  save.textContent = 'Save to field'
  save.addEventListener('click', () => {
    setNativeValue(el, ta.value)
    closeEditor()
  })
  const cancel = document.createElement('button')
  cancel.type = 'button'
  cancel.className = 'ed-cancel'
  cancel.textContent = 'Cancel'
  cancel.addEventListener('click', closeEditor)
  ta.addEventListener('keydown', (ev) => {
    if (ev.key === 'Escape') closeEditor()
    if (ev.key === 'Enter' && (ev.metaKey || ev.ctrlKey)) {
      setNativeValue(el, ta.value)
      closeEditor()
    }
  })
  row.append(save, cancel)
  editor.append(head, ta, row)
  layer!.appendChild(editor)
  positionEditor()
  ta.focus()
}

function positionEditor(): void {
  if (!editor || !editTarget) return
  const r = editTarget.el.getBoundingClientRect()
  const top = r.bottom + 6
  editor.style.top = `${Math.min(top, window.innerHeight - editor.offsetHeight - 8)}px`
  editor.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 288))}px`
}

function closeEditor(): void {
  editor?.remove()
  editor = null
  editTarget = null
}

/** Tear the whole layer down — on re-fill, navigation, or submit. */
export function clearProofMarks(): void {
  window.removeEventListener('scroll', schedule, true)
  window.removeEventListener('resize', schedule)
  document.removeEventListener('submit', clearProofMarks, true)
  closeEditor()
  host?.remove()
  host = root = layer = null
  entries = []
}

// Scoped to the Shadow root, so none of this leaks to the host page. Reduced
// motion drops the highlighter sweep + pulse to plain states.
const LAYER_CSS = `
.layer { position: fixed; inset: 0; pointer-events: none; z-index: 2147483000;
  font-family: var(--ra-font-body); }
.ring { position: fixed; border-radius: 5px; box-sizing: border-box;
  border: 1.5px solid transparent; transition: box-shadow .2s ease; }
.ring.k-draft { border-color: color-mix(in srgb, var(--ra-marigold) 70%, transparent);
  background: color-mix(in srgb, var(--ra-highlight) 16%, transparent); }
.ring.k-choice { border-color: color-mix(in srgb, var(--ra-marigold) 65%, transparent); }
.ring.k-ok { border-color: color-mix(in srgb, var(--ra-ok) 45%, transparent); }
.ring.k-blank, .ring.k-flag { border-color: color-mix(in srgb, var(--ra-gap-hi) 55%, transparent); }
.ring.k-sensitive { border-color: var(--ra-gap); border-style: dashed; }
.ring.k-query { border-color: color-mix(in srgb, var(--ra-marigold) 60%, transparent);
  border-style: dashed; }
.ring.pulse { animation: ra-pulse 1.1s ease-out 2; }
@keyframes ra-pulse {
  0% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--ra-marigold) 70%, transparent); }
  100% { box-shadow: 0 0 0 10px transparent; }
}

.chip { position: fixed; display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 8px; border-radius: 999px; white-space: nowrap;
  background: var(--ra-paper); color: var(--ra-ink);
  border: 1px solid var(--ra-paper-line);
  box-shadow: 0 2px 6px rgba(0,0,0,.28); pointer-events: auto;
  font-family: var(--ra-font-mono); font-size: 10px; letter-spacing: .08em;
  text-transform: uppercase; line-height: 1; }
.chip .glyph { font-family: var(--ra-font-body); font-size: 12px; line-height: 1; }
.chip.k-draft { cursor: pointer; background: var(--ra-highlight); color: var(--ra-ink);
  border-color: var(--ra-marigold); }
.chip.k-draft:hover { filter: brightness(1.04); }
.chip.k-draft:focus-visible { outline: 2px solid var(--ra-accent-ink); outline-offset: 2px; }
.chip.k-choice { background: var(--ra-paper); color: var(--ra-accent-ink);
  border-color: var(--ra-marigold); }
.chip.k-ok { background: var(--ra-desk-2); color: var(--ra-ok); border-color: transparent;
  padding: 3px 6px; }
.chip.k-blank .glyph, .chip.k-flag .glyph { color: var(--ra-gap); }
.chip.k-sensitive { color: var(--ra-gap); border-color: var(--ra-gap); }
.chip.k-query .glyph { color: var(--ra-accent-ink); font-weight: 700; }

.editor { position: fixed; width: 280px; pointer-events: auto; z-index: 2;
  background: var(--ra-desk); color: var(--ra-cream);
  border: 1px solid var(--ra-line); border-radius: var(--ra-radius);
  box-shadow: 0 14px 40px rgba(0,0,0,.55); padding: 10px; }
.ed-head { font-family: var(--ra-font-mono); font-size: 10px; letter-spacing: .16em;
  text-transform: uppercase; color: var(--ra-cream-soft); margin-bottom: 6px; }
.ed-text { width: 100%; min-height: 84px; resize: vertical; box-sizing: border-box;
  background: var(--ra-desk-2); color: var(--ra-cream);
  border: 1px solid var(--ra-line); border-radius: 6px; padding: 8px;
  font-family: var(--ra-font-body); font-size: 13px; line-height: 1.4; }
.ed-text:focus { outline: none; border-color: var(--ra-marigold); }
.ed-row { display: flex; gap: 8px; margin-top: 8px; }
.ed-save { flex: 1; height: 30px; border: 0; border-radius: 6px; cursor: pointer;
  background: var(--ra-marigold); color: var(--ra-ink);
  font-family: var(--ra-font-mono); font-size: 11px; letter-spacing: .1em;
  text-transform: uppercase; }
.ed-cancel { height: 30px; padding: 0 10px; border: 1px solid var(--ra-line);
  border-radius: 6px; background: transparent; color: var(--ra-cream-soft); cursor: pointer;
  font-family: var(--ra-font-mono); font-size: 11px; text-transform: uppercase; }
.ed-save:focus-visible, .ed-cancel:focus-visible { outline: 2px solid var(--ra-marigold);
  outline-offset: 2px; }

@media (prefers-reduced-motion: reduce) {
  .ring, .ring.pulse { animation: none; transition: none; }
}
`
