import { Sheet } from '@/components/ui/Sheet'

// Empty page state on a small sheet with a marigold margin rule — a serif line
// and a pointer to the next action (the T14 onboarding ethos).
export function EmptyState({
  title,
  children,
}: {
  title: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <Sheet sm className="border-l-[3px] border-l-marigold px-5 py-4 text-ink">
      <p className="font-serif text-lg">{title}</p>
      <p className="mt-1 text-sm text-ink-soft">{children}</p>
    </Sheet>
  )
}
