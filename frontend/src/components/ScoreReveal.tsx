import { motion } from 'motion/react'

import { Sheet } from '@/components/ui/Sheet'
import { EASE } from '@/lib/motion'
import { CountUp } from './CountUp'

/** The signature moment: JD-fit before → after, delta animated, on a lit sheet. */
export function ScoreReveal({ before, after }: { before: number; after: number }) {
  const delta = after - before
  return (
    <Sheet className="relative overflow-hidden p-8">
      <div className="flex items-center justify-between">
        <span className="font-mono text-[11px] tracking-[0.28em] text-ink-soft uppercase">
          JD-fit / ATS
        </span>
        {delta !== 0 && (
          <motion.span
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 1.3 }}
            className="rounded-sm bg-highlight px-2.5 py-1 font-mono text-sm font-medium text-ink"
          >
            {delta > 0 ? '+' : ''}
            {delta}
          </motion.span>
        )}
      </div>

      <div className="mt-6 flex items-end gap-6">
        <div>
          <div className="font-mono text-[11px] tracking-[0.15em] text-ink-soft uppercase">before</div>
          <div className="font-mono text-4xl text-ink-soft/60 tabular-nums line-through decoration-ink-soft/40 decoration-1">
            {before}
          </div>
        </div>

        <motion.div
          aria-hidden
          initial={{ opacity: 0, x: -8 }}
          animate={{ opacity: 1, x: 0 }}
          transition={{ delay: 0.4 }}
          className="pb-3 text-3xl text-accent"
        >
          →
        </motion.div>

        <div>
          <div className="font-mono text-[11px] tracking-[0.15em] text-accent uppercase">after</div>
          <div className="flex items-baseline font-mono text-8xl leading-[0.85] font-medium text-ink tabular-nums">
            <CountUp to={after} delay={0.4} />
            <span className="ml-1 text-2xl text-ink-soft">/100</span>
          </div>
        </div>
      </div>

      {/* the score, drawn as a marigold rule sweeping to its mark */}
      <div className="mt-7 h-1.5 overflow-hidden rounded-full bg-ink/10">
        <motion.div
          initial={{ width: `${before}%` }}
          animate={{ width: `${after}%` }}
          transition={{ delay: 0.4, duration: 1.1, ease: EASE }}
          className="h-full rounded-full bg-marigold"
        />
      </div>
    </Sheet>
  )
}
