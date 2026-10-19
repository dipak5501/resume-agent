import { cn } from '@/lib/utils'

// A mono "loading…" line on the desk.
// ponytail: the single seam P2 swaps for paper skeletons — swap here, not per page.
export function Loading({
  children,
  className,
}: {
  children: React.ReactNode
  className?: string
}) {
  return (
    <p className={cn('font-mono text-sm tracking-[0.2em] text-cream-soft uppercase', className)}>
      {children}
    </p>
  )
}
