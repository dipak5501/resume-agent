import { cn } from '@/lib/utils'

// A pulsing placeholder block — reduced-motion safe (motion-reduce:animate-none,
// no JS). Default tone reads on the dark desk; pass e.g. `bg-ink/10` for a
// placeholder sitting inside a paper sheet.
export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn('block animate-pulse rounded bg-cream-soft/10 motion-reduce:animate-none', className)}
    />
  )
}
