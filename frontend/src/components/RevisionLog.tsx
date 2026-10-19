import { motion } from 'motion/react'

import { Sheet } from '@/components/ui/Sheet'
import { rise } from '@/lib/motion'
import type { RoundEntry } from '@/lib/types'

// The proof-rounds log (T22): one docket, perforated into slips - a carbon copy
// per round, punched down the margin. Replaces the single "What changed" list, so
// the whole history stays on the desk instead of only the latest pass.
//
// Informational by design: the PDF on the left is always the LATEST round. Viewing
// or restoring an earlier round is a future ticket, so nothing here is clickable.

/** ▲/▼ against the previous round. Marigold up, muted brick down - honest, never
 *  alarming: a user-directed edit that costs coverage is a trade they chose. */
function Delta({ value }: { value: number }) {
  if (value === 0) {
    return (
      <span className="rounded-sm border border-paper-line px-2 py-0.5 font-mono text-xs text-ink-soft tabular-nums">
        ± 0
      </span>
    )
  }
  const up = value > 0
  return (
    <span
      className={
        up
          ? 'rounded-sm bg-highlight px-2 py-0.5 font-mono text-xs font-medium text-ink tabular-nums'
          : 'rounded-sm border border-gap/30 bg-gap/8 px-2 py-0.5 font-mono text-xs text-gap tabular-nums'
      }
    >
      {up ? `▲ +${value}` : `▼ ${Math.abs(value)}`}
    </span>
  )
}

function Slip({ round, first, current }: { round: RoundEntry; first: boolean; current: boolean }) {
  const dip = round.ats_delta !== null && round.ats_delta < 0 ? Math.abs(round.ats_delta) : 0
  return (
    <li
      aria-current={current ? 'step' : undefined}
      className={`relative pl-8 ${first ? '' : 'mt-6 border-t border-dashed border-paper-line pt-6'}`}
    >
      {/* a punched hole in the docket margin per round, inked in on the current one.
          Offset past the perforation on every slip but the first, so each hole sits
          on the same line as the round label it belongs to. */}
      <span
        aria-hidden
        className={`absolute left-0 size-3.5 rounded-full ${first ? 'top-[5px]' : 'top-[calc(1.5rem+5px)]'} ${
          current
            ? 'border border-marigold bg-marigold shadow-[0_0_0_3px_rgba(243,180,31,0.18)]'
            : 'border border-ink-soft/40 bg-paper'
        }`}
      />

      <div className="flex items-baseline justify-between gap-4">
        <span className="font-mono text-[11px] tracking-[0.18em] text-ink-soft uppercase">
          round {round.index} ·{' '}
          <span className={current ? 'text-ink' : undefined}>
            {round.kind === 'initial' ? 'initial tailoring' : 'your revision'}
          </span>
        </span>
        <span className="flex shrink-0 items-baseline gap-2">
          <span className="font-mono text-lg leading-none text-ink tabular-nums">
            {round.ats_overall}
            <span className="text-xs text-ink-soft">/100</span>
          </span>
          {round.ats_delta !== null && <Delta value={round.ats_delta} />}
        </span>
      </div>

      {/* the user's own words, back in the margin - proof that we heard them */}
      {round.feedback && (
        <blockquote className="mt-3 border-l-2 border-marigold/60 pl-3 font-serif text-[0.95rem] leading-relaxed text-ink-soft italic">
          {round.feedback}
        </blockquote>
      )}

      {round.summary && (
        <p className="mt-3 text-sm leading-relaxed text-ink">{round.summary}</p>
      )}

      {dip > 0 && (
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-ink-soft">
          traded {dip} pt{dip === 1 ? '' : 's'} of keyword coverage for your request.
        </p>
      )}

      {round.changes.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {round.changes.map((c, i) => (
            <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-ink-soft">
              <span aria-hidden className="mt-0.5 font-mono text-[10px] text-marigold tabular-nums">
                {String(i + 1).padStart(2, '0')}
              </span>
              <span>{c}</span>
            </li>
          ))}
        </ul>
      )}

      {!round.summary && round.changes.length === 0 && (
        <p className="mt-3 font-mono text-[11px] text-ink-soft">no notes recorded for this round.</p>
      )}
    </li>
  )
}

export function RevisionLog({ rounds, warnings }: { rounds: RoundEntry[]; warnings: string[] }) {
  if (rounds.length === 0) return null

  return (
    <Sheet as={motion.section} variants={rise} className="p-7">
      <header className="flex items-baseline justify-between gap-4">
        <h2 className="font-serif text-2xl text-ink">Proof rounds</h2>
        <span className="font-mono text-[11px] tracking-[0.15em] text-ink-soft uppercase">
          {rounds.length} round{rounds.length === 1 ? '' : 's'}
        </span>
      </header>

      <ol className="mt-6">
        {rounds.map((r, i) => (
          <Slip key={r.index} round={r} first={i === 0} current={i === rounds.length - 1} />
        ))}
      </ol>

      {warnings.length > 0 && (
        <ul className="mt-6 space-y-1.5 border-t border-paper-line pt-4">
          {warnings.map((w, i) => (
            <li key={i} className="font-mono text-[11px] leading-relaxed text-ink-soft">
              <span className="text-gap">note · </span>
              {w}
            </li>
          ))}
        </ul>
      )}
    </Sheet>
  )
}
