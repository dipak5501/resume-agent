import { Kicker } from './Kicker'

// Shared masthead for the "set up & track" sections — keeps Library, Profile,
// Answers and History speaking the same proofing-desk voice. (Folds in the old
// PageHeading: same markup, now built on the Kicker primitive.)
export function SectionHeading({
  kicker,
  title,
  children,
}: {
  kicker: string
  title: React.ReactNode
  children?: React.ReactNode
}) {
  return (
    <header className="space-y-3">
      <Kicker>{kicker}</Kicker>
      <h1 className="font-serif text-6xl font-medium tracking-[-0.02em] text-cream sm:text-7xl">
        {title}
      </h1>
      {children && <p className="max-w-2xl text-lg leading-relaxed text-cream-soft">{children}</p>}
    </header>
  )
}
