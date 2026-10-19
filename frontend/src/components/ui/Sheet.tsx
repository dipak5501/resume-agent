import type { ComponentPropsWithoutRef, ElementType } from 'react'

import { cn } from '@/lib/utils'

// A sheet of warm paper on the desk (see `.sheet` / `.sheet-sm` in index.css).
// Polymorphic so it can be a page's <div>, a <ul> list, or a `motion.section`
// that carries an entrance animation. `sm` picks the lighter shadow + radius.
// ponytail: the single seam P3 attaches sheet-entrance motion to — one place,
// not a `.sheet` literal repeated across every page.
type SheetProps<T extends ElementType> = {
  as?: T
  sm?: boolean
  className?: string
} & Omit<ComponentPropsWithoutRef<T>, 'as' | 'className'>

export function Sheet<T extends ElementType = 'div'>({ as, sm, className, ...rest }: SheetProps<T>) {
  const Comp = (as ?? 'div') as ElementType
  return <Comp className={cn(sm ? 'sheet-sm' : 'sheet', className)} {...rest} />
}
