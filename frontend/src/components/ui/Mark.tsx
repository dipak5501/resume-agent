import type { ComponentPropsWithoutRef } from 'react'

import { cn } from '@/lib/utils'

// A proofing mark over a keyword: `hl` = highlighter swipe (coverage), `gap` =
// wavy brick underline (a miss). Backed by `.mark-hl` / `.mark-gap` in index.css.
export function Mark({
  kind = 'hl',
  className,
  ...rest
}: { kind?: 'hl' | 'gap' } & ComponentPropsWithoutRef<'span'>) {
  return <span className={cn(kind === 'gap' ? 'mark-gap' : 'mark-hl', className)} {...rest} />
}
