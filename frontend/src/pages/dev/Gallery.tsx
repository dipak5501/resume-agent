import { RevisionLog } from '@/components/RevisionLog'
import { EmptyState } from '@/components/states/EmptyState'
import { ErrorState } from '@/components/states/ErrorState'
import { InlineError } from '@/components/states/InlineError'
import { ListSkeleton } from '@/components/states/ListSkeleton'
import { Loading } from '@/components/states/Loading'
import { Kicker } from '@/components/ui/Kicker'
import { Mark } from '@/components/ui/Mark'
import { SectionHeading } from '@/components/ui/SectionHeading'
import { Sheet } from '@/components/ui/Sheet'
import { Skeleton } from '@/components/ui/Skeleton'
import { Stamp } from '@/components/ui/Stamp'
import type { RoundEntry } from '@/lib/types'

// Dev-only component gallery (mounted only when import.meta.env.DEV — see App.tsx,
// never in the nav or the prod bundle). One place to see + work the whole
// proofing-desk vocabulary. No Storybook: a route is lazier and adds no dep.
function Spec({ name, children }: { name: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="font-mono text-[11px] tracking-[0.26em] text-cream-soft uppercase">{name}</h2>
      {children}
    </section>
  )
}

const ROUNDS: RoundEntry[] = [
  {
    index: 0,
    kind: 'initial',
    feedback: null,
    summary:
      'Condensed the summary to three lines around Go, Kubernetes and Terraform, and swapped the lead project for a JD-specific platform build.',
    ats_overall: 91,
    ats_delta: null,
    changes: ['Rewrote the professional summary', 'Replaced the first project'],
    added: ['Terraform'],
  },
  {
    index: 1,
    kind: 'revision',
    feedback: 'lead with the platform work; tone down the AI/ML framing',
    summary:
      'Reordered the Viasat entry to open on infrastructure work and stripped AI/ML wording from the experience and projects sections.',
    ats_overall: 88,
    ats_delta: -3,
    changes: ['Moved the Terraform/ArgoCD bullet to the top', "Removed 'AI-driven' from the agent bullet"],
    added: [],
  },
  {
    index: 2,
    kind: 'revision',
    feedback: 'add the on-call and incident response experience back in',
    summary: 'Added an on-call rotation bullet under Viasat and surfaced incident response in the skills list.',
    ats_overall: 93,
    ats_delta: 5,
    changes: ['Added an on-call/incident-response bullet'],
    added: ['Incident response'],
  },
]

export default function Gallery() {
  return (
    <div className="mx-auto max-w-4xl space-y-12 px-6 py-16">
      <SectionHeading kicker="dev · gallery" title={<>The vocabulary<span className="text-marigold">.</span></>}>
        Every primitive and page-state in one place. Dev-only — not in the nav, not in prod.
      </SectionHeading>

      <Spec name="Kicker">
        <Kicker>the proofing desk</Kicker>
        <Kicker tone="gap">the press jammed</Kicker>
      </Spec>

      <Spec name="SectionHeading">
        <SectionHeading kicker="set up & track · example" title={<>Your details<span className="text-marigold">.</span></>}>
          The masthead used across the track pages.
        </SectionHeading>
      </Spec>

      <Spec name="Sheet">
        <Sheet className="p-7">
          <p className="text-ink">A sheet of warm paper on the desk.</p>
        </Sheet>
      </Spec>

      <Spec name="Sheet · sm (list)">
        <Sheet as="ul" sm className="divide-y divide-border overflow-hidden">
          {['resume-swe.tex', 'resume-ml.tex'].map((f) => (
            <li key={f} className="px-4 py-2.5 font-mono text-sm text-ink">{f}</li>
          ))}
        </Sheet>
      </Spec>

      <Spec name="Mark">
        <div className="flex flex-wrap gap-x-2 gap-y-2.5 text-lg">
          <Mark>Kubernetes</Mark>
          <Mark>Terraform</Mark>
          <Mark kind="gap">Rust</Mark>
        </div>
      </Spec>

      <Spec name="Stamp">
        <div className="relative h-28">
          <Stamp className="absolute top-4 left-8" sub={<>one page · {new Date().getFullYear()}</>} />
        </div>
      </Spec>

      <Spec name="RevisionLog (T22 · proof rounds)">
        <RevisionLog rounds={ROUNDS} warnings={['no change made - round not counted']} />
      </Spec>

      <Spec name="EmptyState">
        <EmptyState title="An empty desk.">
          Add your first source below — then tailor it to a job.
        </EmptyState>
      </Spec>

      <Spec name="Loading">
        <Loading>loading the desk…</Loading>
      </Spec>

      <Spec name="Skeleton">
        <div className="max-w-sm space-y-2">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="h-3.5 w-1/2" />
        </div>
      </Spec>

      <Spec name="ListSkeleton (paper loading)">
        <ListSkeleton rows={3} />
      </Spec>

      <Spec name="InlineError (recoverable)">
        <InlineError onRetry={() => {}}>Couldn&rsquo;t load this — is the backend running?</InlineError>
      </Spec>

      <Spec name="ErrorState">
        <ErrorState kicker="off the desk" title="That run isn't here" action={{ label: 'New brief', onClick: () => {} }}>
          It may have expired. Start a fresh brief.
        </ErrorState>
      </Spec>
    </div>
  )
}
