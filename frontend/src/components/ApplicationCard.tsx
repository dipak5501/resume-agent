import { useState } from 'react'
import { motion } from 'motion/react'

import { ApplicationAnswers } from '@/components/ApplicationAnswers'
import { FeedbackBox } from '@/components/FeedbackBox'
import { Sheet } from '@/components/ui/Sheet'
import { rise } from '@/lib/motion'
import type { JobAnswer } from '@/lib/types'

// One card, two jobs (T24): fix the résumé, or write the words that go beside it.
// The mode is an explicit choice — guessing it from the text would spend a
// revision round on a question, or draft prose when an edit was wanted.

type Mode = 'revise' | 'answer'

const TABS: { id: Mode; label: string; blurb: string }[] = [
  {
    id: 'revise',
    label: 'Revise résumé',
    blurb: 'Tell us what to change and we run another proof round on the page itself.',
  },
  {
    id: 'answer',
    label: 'Answer a question',
    blurb:
      'Draft an answer to an application question, grounded on the tailored résumé above — then copy it into the form.',
  },
]

export function ApplicationCard({
  jobId,
  round,
  answers,
}: {
  jobId: string
  round: number
  answers: JobAnswer[]
}) {
  const [mode, setMode] = useState<Mode>('revise')
  const active = TABS.find((t) => t.id === mode)!

  return (
    <Sheet as={motion.section} variants={rise} className="p-7">
      <h2 className="font-serif text-2xl text-ink">Work on this application</h2>

      {/* two tabs on a shared rule — the inked one slides between them */}
      <div role="tablist" aria-label="Application task" className="mt-5 flex gap-7 border-b border-paper-line">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            id={`tab-${t.id}`}
            aria-selected={mode === t.id}
            aria-controls={`panel-${t.id}`}
            onClick={() => setMode(t.id)}
            className={`relative -mb-px pb-2.5 font-mono text-[11px] tracking-[0.18em] uppercase transition-colors ${
              mode === t.id ? 'text-ink' : 'text-ink-soft hover:text-ink'
            }`}
          >
            {t.label}
            {mode === t.id && (
              <motion.span
                layoutId="application-tab-rule"
                aria-hidden
                className="absolute inset-x-0 -bottom-px h-[2px] bg-marigold"
              />
            )}
          </button>
        ))}
      </div>

      <div role="tabpanel" id={`panel-${mode}`} aria-labelledby={`tab-${mode}`}>
        <p className="mt-4 text-sm leading-relaxed text-ink-soft">{active.blurb}</p>
        {mode === 'revise' ? (
          <FeedbackBox jobId={jobId} round={round} />
        ) : (
          <ApplicationAnswers jobId={jobId} answers={answers} />
        )}
      </div>
    </Sheet>
  )
}
