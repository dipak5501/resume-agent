import { Skeleton } from '@/components/ui/Skeleton'
import { Sheet } from '@/components/ui/Sheet'

// Paper-sheet loading state for row lists (Library / History / Answers): faint
// ink bars on a small sheet, so a list reads as paper materializing — not a spinner.
export function ListSkeleton({ rows = 4 }: { rows?: number }) {
  return (
    <Sheet as="ul" sm className="divide-y divide-border overflow-hidden">
      {Array.from({ length: rows }).map((_, i) => (
        <li key={i} className="flex items-center gap-3 px-4 py-3.5">
          <Skeleton className="h-3.5 w-2/5 bg-ink/10" />
          <Skeleton className="ml-auto h-3.5 w-16 bg-ink/10" />
        </li>
      ))}
    </Sheet>
  )
}
