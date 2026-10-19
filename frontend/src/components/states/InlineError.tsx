import { Sheet } from '@/components/ui/Sheet'

// Recoverable inline error on a small sheet with a brick-red (gap) margin rule —
// honest text plus a Retry that re-runs the query. Sits under a SectionHeading so
// the masthead survives (unlike the full-page ErrorState).
export function InlineError({
  children,
  onRetry,
}: {
  children: React.ReactNode
  onRetry?: () => void
}) {
  return (
    <Sheet
      sm
      role="alert"
      className="flex items-center justify-between gap-4 border-l-[3px] border-l-gap px-5 py-4 text-ink"
    >
      <p className="text-sm text-ink-soft">{children}</p>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded px-2 py-1 font-mono text-xs tracking-[0.15em] text-accent uppercase underline-offset-2 hover:underline"
        >
          retry
        </button>
      )}
    </Sheet>
  )
}
