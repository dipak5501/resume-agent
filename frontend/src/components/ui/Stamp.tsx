import { cn } from '@/lib/utils'

// The "Proof Approved" rubber stamp (`.stamp` / `.stamp-in` in index.css) — the
// Result payoff. Positioning is the caller's (className); the ink is the primitive.
export function Stamp({ className, sub }: { className?: string; sub?: React.ReactNode }) {
  return (
    <div className={cn('stamp stamp-in text-[0.72rem] leading-tight tracking-[0.16em]', className)}>
      <span>Proof</span>
      <span>Approved</span>
      {sub && <span className="mt-0.5 text-[0.5rem] tracking-[0.14em] opacity-80">{sub}</span>}
    </div>
  )
}
