import { useEffect, useState } from 'react'

import { flagKind, type MarkKind, YOURS } from '../shared/mark-kind'
import { sendToBackground } from '../shared/messaging'
import type { FillResult, JobSummary, PlanItem } from '../shared/types'

/** Ask the content script in the active tab to fill the form. */
function fillActiveTab(jobId: string | null): Promise<FillResult> {
  return new Promise((resolve, reject) => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return reject(new Error('No active tab.'))
      chrome.tabs.sendMessage(tab.id, { type: 'FILL', jobId }, (resp) => {
        if (chrome.runtime.lastError) {
          return reject(
            new Error('Open a supported application page (Greenhouse · Lever · Ashby · Workday) and reload it once after installing.'),
          )
        }
        resolve(resp as FillResult)
      })
    })
  })
}

/** Proactively ask whether this tab has a form — drives the "no page" state. */
function detectActiveTab(): Promise<boolean> {
  return new Promise((resolve) => {
    chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
      if (!tab?.id) return resolve(false)
      chrome.tabs.sendMessage(tab.id, { type: 'DETECT' }, (resp) => {
        if (chrome.runtime.lastError) return resolve(false) // no content script here
        resolve(Boolean(resp?.formPresent))
      })
    })
  })
}

/** Jump-to-field: scroll + focus a flagged field on the page (T15). */
function focusFieldInTab(ref: number): void {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (tab?.id != null) chrome.tabs.sendMessage(tab.id, { type: 'FOCUS_FIELD', field_ref: ref })
  })
}

// Popup React state is destroyed every time the popup closes, so the review
// summary vanishes even though the page stays filled. Stash the last result per
// tab in session storage and restore it on reopen (cleared when the browser closes).
function withActiveTabId(cb: (id: number) => void): void {
  chrome.tabs.query({ active: true, currentWindow: true }, ([tab]) => {
    if (tab?.id != null) cb(tab.id)
  })
}
function saveResult(r: FillResult): void {
  withActiveTabId((id) => chrome.storage.session.set({ [`fill_${id}`]: r }))
}
function loadResult(cb: (r: FillResult | null) => void): void {
  withActiveTabId((id) =>
    chrome.storage.session.get(`fill_${id}`, (o) => cb((o[`fill_${id}`] as FillResult) ?? null)),
  )
}

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function App() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [onForm, setOnForm] = useState<boolean | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<FillResult | null>(null)
  const [fillError, setFillError] = useState<string | null>(null)

  useEffect(() => {
    sendToBackground<JobSummary[]>({ type: 'LIST_JOBS' })
      .then((all) => {
        const ready = all.filter((j) => j.has_pdf)
        setJobs(ready)
        setSelected(ready[0]?.id ?? null)
      })
      .catch((e) => setLoadError(String(e.message ?? e)))
    detectActiveTab().then(setOnForm)
    loadResult((r) => r && setResult(r)) // restore the last fill's review summary
  }, [])

  async function onFill() {
    setBusy(true)
    setResult(null)
    setFillError(null)
    try {
      const r = await fillActiveTab(selected)
      if (r.error) setFillError(r.error)
      setResult(r)
      saveResult(r) // persist so closing/reopening the popup keeps the review
    } catch (e) {
      setFillError(String((e as Error).message ?? e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="mast">
        <span className="wordmark">
          Résumé<span className="dot">·</span>Proof
        </span>
        <span className="kicker">assisted autofill</span>
      </header>

      {onForm === false && !result ? (
        <NoForm />
      ) : result ? (
        <Review result={result} onRefill={onFill} busy={busy} />
      ) : (
        <>
          <p className="framing">
            I&rsquo;ll fill contact fields from your profile, draft any screening answers, and attach
            your tailored résumé — then <strong>stop</strong>. You review every mark and submit
            yourself.
          </p>

          <section>
            <h2>Apply with</h2>
            {loadError && <p className="err">Backend not reachable — is it running on 127.0.0.1:8000?</p>}
            {jobs && jobs.length === 0 && (
              <p className="muted">No finished runs yet. Tailor a résumé first, then come back.</p>
            )}
            {jobs && jobs.length > 0 && (
              <ul className="runs">
                {jobs.map((j) => (
                  <li key={j.id}>
                    <label>
                      <input
                        type="radio"
                        name="run"
                        checked={selected === j.id}
                        onChange={() => setSelected(j.id)}
                      />
                      <span className="run-title">{j.title}</span>
                      <span className="run-meta">{timeAgo(j.created_at)}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <button className="fill" onClick={onFill} disabled={busy}>
            {busy ? 'Marking the proof…' : selected ? 'Fill form + attach résumé' : 'Fill contact fields'}
          </button>
          <p className="never">This never submits the form for you.</p>
          {fillError && <p className="err">{fillError}</p>}
        </>
      )}
    </div>
  )
}

function NoForm() {
  return (
    <section className="noform">
      <p className="noform-mark">‸</p>
      <h2>No application on this page</h2>
      <p className="muted">
        Open a job&rsquo;s <strong>apply</strong> form on Greenhouse, Lever, Ashby or Workday — then
        reopen this popup. Reload the page once if you just installed the extension.
      </p>
    </section>
  )
}

// The review dashboard (T15): the popup is the index, the page is the marked-up
// proof. Counts + the list of everything that needs the user's eyes, each row
// jumping to its field on the page.
function Review({ result, onRefill, busy }: { result: FillResult; onRefill: () => void; busy: boolean }) {
  // needsReview fills split by kind: free-text AI drafts (editable, save-to-bank)
  // vs. radio/select selections we made (review the pick, not the prose). (T17)
  const textDrafts = result.filled.filter((p) => p.needsReview && p.control !== 'choice')
  const choiceReviews = result.filled.filter((p) => p.needsReview && p.control === 'choice')
  const filledOk = result.filled.filter((p) => !p.needsReview)
  // Split flagged into the ones worth an individual row (sensitive / low-confidence)
  // and the plain "we couldn't map this" bunch — the latter is just a count, not
  // a per-field mark, so the review list (and the page) stay readable.
  const meaningfulFlags = result.flagged.filter((it) => flagKind(it) !== 'flag')
  const genericFlags = result.flagged.filter((it) => flagKind(it) === 'flag' && it.reason !== YOURS)
  const rows = [
    ...textDrafts.map((it) => ({ it, kind: 'draft' as MarkKind })),
    ...choiceReviews.map((it) => ({ it, kind: 'choice' as MarkKind })),
    ...meaningfulFlags.map((it) => ({ it, kind: flagKind(it) as MarkKind })),
    ...result.blank.map((it) => ({ it, kind: 'blank' as MarkKind })),
  ]

  return (
    <section className="review">
      <p className="framing done">Here&rsquo;s what I marked. Check each one, then submit yourself.</p>

      <div className="tally">
        <Tally n={filledOk.length} label="filled" tone="ok" />
        <Tally n={textDrafts.length + choiceReviews.length} label="to review" tone="draft" />
        <Tally n={result.blank.length} label="blank" tone="warn" />
        <Tally n={result.attached.length} label="résumé" tone="ok" glyph="§" />
      </div>

      {rows.length === 0 && genericFlags.length === 0 ? (
        <p className="allclear">✓ All clear — nothing flagged. Give it a final read and submit.</p>
      ) : (
        <>
          {rows.length > 0 && <h2>Needs your eyes</h2>}
          <ul className="marks">
            {rows.map(({ it, kind }) => (
              <MarkRow key={it.field_ref} it={it} kind={kind} />
            ))}
          </ul>
          {genericFlags.length > 0 && (
            <p className="leftover">
              + {genericFlags.length} field{genericFlags.length > 1 ? 's' : ''} we couldn&rsquo;t map —
              you&rsquo;ll fill {genericFlags.length > 1 ? 'those' : 'that'} yourself.
            </p>
          )}
        </>
      )}

      <button className="fill ghost" onClick={onRefill} disabled={busy}>
        {busy ? 'Marking…' : 'Re-mark the proof'}
      </button>
      <p className="never">This never submits the form for you.</p>
      {result.error && <p className="err">{result.error}</p>}
    </section>
  )
}

// 'ok' never reaches the review list, but keep the map total over MarkKind.
const KIND_LABEL: Record<MarkKind, string> = {
  draft: 'AI draft',
  choice: 'answered',
  ok: 'filled',
  blank: 'blank',
  sensitive: 'sensitive',
  query: 'check',
  flag: 'for you',
}

function MarkRow({ it, kind }: { it: PlanItem; kind: MarkKind }) {
  return (
    <li className={`mark k-${kind}`}>
      <button className="mark-jump" onClick={() => focusFieldInTab(it.field_ref)} title="Show on page">
        <span className={`badge b-${kind}`}>{KIND_LABEL[kind]}</span>
        <span className="mark-label">{it.label}</span>
      </button>
      {kind === 'choice' ? (
        <p className="mark-reason">
          selected “{it.value}”{it.reason ? ` · ${it.reason}` : ''}
        </p>
      ) : (
        it.reason && <p className="mark-reason">{it.reason}</p>
      )}
      {kind === 'draft' && <SaveToBank item={it} />}
    </li>
  )
}

/** Promote a drafted answer into the reusable answer bank (T13). */
function SaveToBank({ item }: { item: PlanItem }) {
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  if (item.source === 'bank_adapted') return null // already in the bank
  async function save() {
    setState('saving')
    try {
      await sendToBackground({ type: 'SAVE_ANSWER', question: item.label, answer: item.value ?? '' })
      setState('saved')
    } catch {
      setState('error')
    }
  }
  if (state === 'saved') return <span className="saved">saved to bank ✓</span>
  return (
    <button className="save-bank" onClick={save} disabled={state === 'saving'}>
      {state === 'error' ? 'retry' : 'save to bank'}
    </button>
  )
}

function Tally({ n, label, tone, glyph }: { n: number; label: string; tone: string; glyph?: string }) {
  return (
    <div className={`t t-${tone}`}>
      <span className="t-n">{glyph && n > 0 ? glyph : n}</span>
      <span className="t-l">{label}</span>
    </div>
  )
}
