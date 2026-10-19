import { motion } from 'motion/react'

import { ErrorState } from '@/components/states/ErrorState'
import { StepProgress } from '@/components/StepProgress'
import { Kicker } from '@/components/ui/Kicker'
import { Sheet } from '@/components/ui/Sheet'
import type { Job } from '@/lib/types'

export function Run({ job, onStartOver }: { job: Job; onStartOver: () => void }) {
  if (job.status === 'error') {
    return (
      <ErrorState
        kicker="the press jammed"
        title="Something went wrong"
        action={{ label: 'Start over', onClick: onStartOver }}
      >
        {job.error}
      </ErrorState>
    )
  }

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0, transition: { duration: 0.25 } }}
      className="mx-auto max-w-3xl px-6 py-20 lg:py-28"
    >
      <div className="flex items-center gap-3">
        <span className="relative flex h-2.5 w-2.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-marigold opacity-70" />
          <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-marigold" />
        </span>
        <Kicker>
          {job.round > 0 ? `revision ${job.round} · marking` : 'marking up the proof'}
        </Kicker>
      </div>

      <h2 className="mt-5 font-serif text-6xl leading-[0.95] tracking-[-0.02em] text-cream lg:text-7xl">
        Tailoring in progress<span className="text-marigold">.</span>
      </h2>
      <p className="mt-5 max-w-xl text-lg leading-relaxed text-cream-soft">
        Select &rarr; baseline &rarr; improve &rarr; quality gate. This takes a few minutes — leave it
        running while the press marks the proof.
      </p>

      <Sheet className="mt-12 p-8 lg:p-10">
        <div className="mb-6 flex items-baseline justify-between border-b border-paper-line pb-4">
          <span className="font-mono text-[11px] tracking-[0.28em] text-ink-soft uppercase">
            proof marks
          </span>
          <span className="font-mono text-[11px] tracking-[0.28em] text-accent uppercase">live</span>
        </div>
        <StepProgress progress={job.progress} status={job.status} />
      </Sheet>

      <button
        onClick={onStartOver}
        className="mt-8 font-mono text-xs tracking-[0.2em] text-cream-soft uppercase underline-offset-4 transition hover:text-cream hover:underline"
      >
        cancel &amp; start over
      </button>
    </motion.div>
  )
}
