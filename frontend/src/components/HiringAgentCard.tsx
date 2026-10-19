import { Sheet } from '@/components/ui/Sheet'
import type { HiringAgentReport } from '@/lib/types'

const CATEGORY_MAX: Record<string, number> = {
  open_source: 35,
  self_projects: 30,
  production: 25,
  technical_skills: 10,
}

const label = (k: string) => k.replace(/_/g, ' ')

export function HiringAgentCard({ report }: { report: HiringAgentReport }) {
  return (
    <Sheet as="section" className="p-7">
      <header className="flex items-baseline justify-between">
        <h3 className="font-serif text-2xl text-ink">Quality gate</h3>
        <div className="font-mono text-3xl font-medium text-ink tabular-nums">
          {Math.round(report.overall)}
          <span className="text-base text-ink-soft">/120</span>
        </div>
      </header>

      <div className="mt-6 space-y-3">
        {Object.entries(report.categories).map(([k, v]) => {
          const max = CATEGORY_MAX[k] ?? 100
          return (
            <div key={k} className="grid grid-cols-[9rem_1fr_3rem] items-center gap-3">
              <span className="font-mono text-xs text-ink-soft capitalize">{label(k)}</span>
              <span className="h-1.5 overflow-hidden rounded-full bg-ink/10">
                <span
                  className="block h-full rounded-full bg-marigold"
                  style={{ width: `${Math.min(100, (v / max) * 100)}%` }}
                />
              </span>
              <span className="text-right font-mono text-xs text-ink tabular-nums">
                {v}/{max}
              </span>
            </div>
          )
        })}
      </div>

      {report.note && (
        <p className="mt-6 border-l-[3px] border-marigold pl-4 text-sm leading-relaxed text-ink-soft italic">
          {report.note}
        </p>
      )}

      {report.advice.length > 0 && (
        <div className="mt-6">
          <div className="mb-2.5 font-mono text-[11px] tracking-[0.22em] text-ink-soft uppercase">
            honest levers
          </div>
          <ul className="space-y-1.5">
            {report.advice.map((a, i) => (
              <li key={i} className="flex gap-2 text-sm text-ink">
                <span aria-hidden className="text-accent">
                  ✎
                </span>
                {a}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Sheet>
  )
}
