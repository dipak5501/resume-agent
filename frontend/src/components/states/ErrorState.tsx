import { Kicker } from '@/components/ui/Kicker'

// Full-page error state (the "press jammed" / "off the desk" layout): a gap-tone
// kicker, a serif line, an honest note, and one recovery action.
export function ErrorState({
  kicker,
  title,
  children,
  action,
}: {
  kicker: string
  title: React.ReactNode
  children: React.ReactNode
  action: { label: string; onClick: () => void }
}) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-28 text-center">
      <Kicker tone="gap">{kicker}</Kicker>
      <h2 className="mt-4 font-serif text-5xl text-cream">{title}</h2>
      <p className="mx-auto mt-4 max-w-md font-mono text-sm text-cream-soft">{children}</p>
      <button
        onClick={action.onClick}
        className="mt-9 h-12 rounded-md border border-cream/25 px-7 font-mono text-sm tracking-[0.2em] text-cream uppercase transition hover:bg-cream/10 focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-none"
      >
        {action.label}
      </button>
    </div>
  )
}
