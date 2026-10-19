import { cn } from '@/lib/utils'

// The page eyebrow: a mono, wide-tracked, uppercase label above a display title.
// `tone` picks the ink — marigold (default) or gap (an error's brick red).
export function Kicker({
  tone = 'marigold',
  className,
  children,
}: {
  tone?: 'marigold' | 'gap'
  className?: string
  children: React.ReactNode
}) {
  const ink = tone === 'gap' ? 'text-gap-hi' : 'text-marigold'
  return <p className={cn('font-mono text-sm tracking-[0.34em] uppercase', ink, className)}>{children}</p>
}
