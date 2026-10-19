import type { RequirementVerdict } from '@/lib/types'

const MARK = { meets: '✓', unclear: '?', not_met: '✗' } as const
const LABEL = { meets: 'shown', unclear: 'not clearly shown', not_met: 'not shown' } as const
const TONE = { meets: 'text-accent', unclear: 'text-ink-soft', not_met: 'text-gap' } as const

// T34: what a screener's AI checks - each requirement, its verdict and the quote that
// proves it. Musts first; a gap tells the user what to evidence before applying.
// The mark is role="img": ARIA 1.2 forbids naming a plain span, so its label was ignored.
export function RequirementChecks({ requirements }: { requirements: RequirementVerdict[] }) {
  const rows = [...requirements].sort((a, b) => Number(a.priority !== 'must') - Number(b.priority !== 'must'))
  const shown = requirements.filter((r) => r.verdict === 'meets').length
  return (
    <div>
      <div className="mb-4 font-mono text-[11px] tracking-[0.22em] text-ink-soft uppercase">
        shown &middot; {shown} of {requirements.length}
      </div>
      <ul className="divide-y divide-paper-line">
        {rows.map((r, i) => (
          <li key={`${i}-${r.text}`} className="grid grid-cols-[1.25rem_1fr] gap-x-3 py-3">
            <span
              role="img"
              aria-label={LABEL[r.verdict]}
              className={`font-mono text-sm ${TONE[r.verdict]}`}
            >
              {MARK[r.verdict]}
            </span>
            <div className="min-w-0">
              <p className="text-sm leading-snug text-ink">
                {r.text}
                {r.priority === 'should' && (
                  <span className="ml-2 font-mono text-[10px] tracking-[0.18em] text-ink-soft uppercase">
                    preferred
                  </span>
                )}
              </p>
              {r.evidence ? (
                <p className="mt-1 text-xs leading-relaxed break-words text-ink-soft italic">&ldquo;{r.evidence}&rdquo;</p>
              ) : (
                <p className={`mt-1 font-mono text-[11px] ${TONE[r.verdict]}`}>{LABEL[r.verdict]} on the page</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
