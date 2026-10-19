import { useState } from 'react'

import { InlineError } from '@/components/states/InlineError'
import { ListSkeleton } from '@/components/states/ListSkeleton'
import { Button } from '@/components/ui/button'
import { useAnswers, useCreateAnswer, useDeleteAnswer, useUpdateAnswer } from '@/hooks/useAnswers'
import type { Answer, AnswerMode } from '@/lib/types'

// Human labels for the seeded canonical-core keys (backend canonical.py).
const LABELS: Record<string, string> = {
  salary_expectation: 'Salary expectation',
  work_authorization: 'Work authorization',
  requires_sponsorship: 'Requires visa sponsorship',
  notice_period: 'Notice period',
  willing_to_relocate: 'Willing to relocate',
  preferred_location_remote: 'Location / remote preference',
  earliest_start_date: 'Earliest start date',
  years_experience: 'Years of experience',
  how_heard_about_us: 'How you heard about us',
  why_leaving: 'Why leaving your current role',
  why_company: 'Why this company',
  tell_me_about_yourself: 'Tell me about yourself',
}

const inputCls =
  'w-full rounded-md border border-cream-soft/20 bg-transparent px-3 py-2.5 font-mono text-sm text-cream placeholder:text-cream-soft/40 focus:border-marigold focus:outline-none'

export function AnswerBank() {
  const { data: answers, isPending, isError, refetch } = useAnswers()
  const create = useCreateAnswer()
  const core = (answers ?? []).filter((a) => a.canonical)
  const custom = (answers ?? []).filter((a) => !a.canonical)

  const [q, setQ] = useState('')
  const [a, setA] = useState('')
  const [mode, setMode] = useState<AnswerMode>('verbatim')

  function addCustom() {
    if (!q.trim()) return
    create.mutate({ question: q, answer: a, mode }, { onSuccess: () => (setQ(''), setA('')) })
  }

  return (
    <div className="space-y-4">
      {isPending ? (
        <ListSkeleton rows={6} />
      ) : isError ? (
        <InlineError onRetry={() => refetch()}>
          Couldn&rsquo;t load your answer bank — is the backend running?
        </InlineError>
      ) : (
        <ul className="space-y-3">
          {core.map((row) => (
            <Row key={row.id} row={row} title={LABELS[row.canonical!] ?? row.canonical!} />
          ))}
          {custom.map((row) => (
            <Row key={row.id} row={row} title={row.question ?? '(custom)'} deletable />
          ))}
        </ul>
      )}

      {/* add a custom Q&A */}
      <div className="space-y-3 rounded-md border border-dashed border-cream-soft/20 p-4">
        <p className="font-mono text-[10px] tracking-[0.22em] text-cream-soft uppercase">Add a custom question</p>
        <input className={inputCls} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. Do you have a security clearance?" />
        <textarea className={inputCls} rows={2} value={a} onChange={(e) => setA(e.target.value)} placeholder="Your answer (leave blank to have it drafted)" />
        <div className="flex items-center gap-3">
          <ModeToggle mode={mode} onChange={setMode} />
          <Button
            onClick={addCustom}
            disabled={!q.trim() || create.isPending}
            className="h-9 rounded-md bg-cream-soft/10 px-4 font-mono text-xs tracking-[0.15em] text-cream uppercase transition hover:bg-cream-soft/20 disabled:opacity-40"
          >
            {create.isPending ? 'adding…' : 'Add'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/** One editable row. Saves the answer on blur and the mode on change (only when
 *  changed) — no separate save button to click. */
function Row({ row, title, deletable }: { row: Answer; title: string; deletable?: boolean }) {
  const update = useUpdateAnswer()
  const del = useDeleteAnswer()
  const [val, setVal] = useState(row.answer)
  const mode = row.mode as AnswerMode

  const save = (next: Partial<{ answer: string; mode: AnswerMode }>) =>
    update.mutate({ id: row.id, body: { question: row.question, answer: next.answer ?? val, mode: next.mode ?? mode } })

  return (
    <li className="space-y-2 rounded-md border border-cream-soft/10 bg-cream-soft/[0.03] p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-sm text-cream">{title}</span>
        <span className="flex shrink-0 items-center gap-2">
          <ModeToggle mode={mode} onChange={(m) => save({ mode: m })} />
          {deletable && (
            <button
              onClick={() => del.mutate(row.id)}
              aria-label={`Delete ${title}`}
              className="rounded px-2 py-1 font-mono text-xs text-cream-soft hover:text-gap-hi"
            >
              remove
            </button>
          )}
        </span>
      </div>
      <textarea
        className={inputCls}
        rows={mode === 'adaptable' ? 3 : 1}
        value={val}
        onChange={(e) => setVal(e.target.value)}
        onBlur={() => val !== row.answer && save({ answer: val })}
        placeholder={mode === 'adaptable' ? 'Template to tailor per job…' : 'Your answer…'}
      />
    </li>
  )
}

function ModeToggle({ mode, onChange }: { mode: AnswerMode; onChange: (m: AnswerMode) => void }) {
  return (
    <select
      value={mode}
      onChange={(e) => onChange(e.target.value as AnswerMode)}
      className="rounded border border-cream-soft/20 bg-ink px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-cream-soft uppercase focus:border-marigold focus:outline-none"
      aria-label="answer mode"
    >
      <option value="verbatim">verbatim</option>
      <option value="adaptable">adaptable</option>
    </select>
  )
}
