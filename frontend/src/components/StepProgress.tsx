import { AnimatePresence, motion } from 'motion/react'

import { EASE } from '@/lib/motion'
import type { JobStatus } from '@/lib/types'

export function StepProgress({
  progress,
  status,
}: {
  progress: string[]
  status: JobStatus
}) {
  const steps = progress.length ? progress : ['queued — warming up the press']
  return (
    <ol className="divide-y divide-paper-line">
      <AnimatePresence initial={false}>
        {steps.map((step, i) => {
          const isLast = i === steps.length - 1
          const active = isLast && (status === 'running' || status === 'queued')
          return (
            <motion.li
              key={`${i}-${step}`}
              initial={{ opacity: 0, x: -10 }}
              animate={{ opacity: 1, x: 0 }}
              transition={{ duration: 0.4, ease: EASE }}
              className="flex items-center gap-4 py-3.5 first:pt-0 last:pb-0"
            >
              <span className="w-4 shrink-0 text-center font-mono text-xs text-ink-soft/70 tabular-nums">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span aria-hidden className="w-5 shrink-0 text-center text-lg text-accent">
                {active ? (
                  <motion.span
                    animate={{ rotate: [0, -14, 0], opacity: [1, 0.45, 1] }}
                    transition={{ repeat: Infinity, duration: 1.4 }}
                    className="inline-block"
                  >
                    ✎
                  </motion.span>
                ) : (
                  '✓'
                )}
              </span>
              <span className={active ? 'text-lg text-ink' : 'text-lg text-ink-soft'}>{step}</span>
            </motion.li>
          )
        })}
      </AnimatePresence>
    </ol>
  )
}
