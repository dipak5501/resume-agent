import { Mark } from '@/components/ui/Mark'

export function KeywordMarks({ matched, missing }: { matched: string[]; missing: string[] }) {
  return (
    <div className="space-y-5">
      <div>
        <div className="mb-3 font-mono text-[11px] tracking-[0.22em] text-ink-soft uppercase">
          covered &middot; {matched.length}
        </div>
        <div className="flex flex-wrap gap-x-1.5 gap-y-2.5 text-lg leading-relaxed">
          {matched.length === 0 && <span className="text-sm text-ink-soft">—</span>}
          {matched.map((k, i) => (
            <Mark key={k} style={{ animationDelay: `${0.5 + i * 0.05}s` }}>
              {k}
            </Mark>
          ))}
        </div>
      </div>

      {missing.length > 0 && (
        <div className="border-t border-paper-line pt-4">
          <div className="mb-3 font-mono text-[11px] tracking-[0.22em] text-gap uppercase">
            gaps &middot; {missing.length}
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-lg">
            {missing.map((k) => (
              <Mark key={k} kind="gap">
                {k}
              </Mark>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
