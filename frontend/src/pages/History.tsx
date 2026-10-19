import { motion } from 'motion/react'
import { Link } from 'react-router-dom'

import { MarkAppliedButton } from '@/components/MarkAppliedButton'
import { EmptyState } from '@/components/states/EmptyState'
import { InlineError } from '@/components/states/InlineError'
import { ListSkeleton } from '@/components/states/ListSkeleton'
import { SectionHeading } from '@/components/ui/SectionHeading'
import { Sheet } from '@/components/ui/Sheet'
import { useJobsList } from '@/hooks/useJobs'
import { rise, stagger, useEntrance } from '@/lib/motion'
import type { JobStatus, JobSummary } from '@/lib/types'

function timeAgo(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

const STATUS: Record<JobStatus, { label: string; cls: string }> = {
  done: { label: 'proofed', cls: 'bg-marigold/20 text-marigold' },
  running: { label: 'on the press', cls: 'bg-cream-soft/15 text-cream-soft' },
  queued: { label: 'queued', cls: 'bg-cream-soft/15 text-cream-soft' },
  error: { label: 'jammed', cls: 'bg-gap/20 text-gap-hi' },
}

// Run history (T14) over GET /jobs — the same endpoint the extension picker
// reads. Each row reopens into its /tailor/:id route (Result if it finished).
export function History() {
  const { data: jobs, isPending, isError, refetch } = useJobsList()
  const entrance = useEntrance()

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto max-w-4xl space-y-8 px-6 py-16 lg:py-20"
    >
      <motion.div variants={rise}>
        <SectionHeading kicker="set up & track · history" title={<>Past proofs<span className="text-marigold">.</span></>}>
          Every run you&rsquo;ve sent to the press. Reopen one to view its proof, scores and the
          tailored PDF.
        </SectionHeading>
      </motion.div>

      <motion.div variants={rise}>
        {isPending && <ListSkeleton />}
        {isError && (
          <InlineError onRetry={() => refetch()}>
            Couldn&rsquo;t load your history — is the backend running?
          </InlineError>
        )}

        {jobs && jobs.length === 0 && (
          <EmptyState title="Nothing filed yet.">
            <Link to="/" className="text-accent underline-offset-2 hover:underline">
              Tailor your first résumé
            </Link>{' '}
            and it&rsquo;ll land here.
          </EmptyState>
        )}

        {jobs && jobs.length > 0 && (
          <Sheet as="ul" sm className="divide-y divide-border overflow-hidden">
            {jobs.map((j) => (
              <Row key={j.id} job={j} />
            ))}
          </Sheet>
        )}
      </motion.div>
    </motion.div>
  )
}

function Row({ job }: { job: JobSummary }) {
  const s = job.applied
    ? { label: 'applied', cls: 'bg-marigold/20 text-marigold' }
    : STATUS[job.status]
  const canFile = job.status === 'done' && job.has_pdf && !job.applied
  return (
    <li className="group flex items-center gap-3 px-4 py-3.5 transition hover:bg-paper-edge">
      <Link
        to={`/tailor/${job.id}`}
        className="flex min-w-0 flex-1 items-center gap-3 focus-visible:outline-none"
      >
        <span className="min-w-0 flex-1">
          <span className="block truncate font-mono text-sm text-ink">{job.title}</span>
          <span className="font-mono text-[11px] text-ink-soft">{timeAgo(job.created_at)}</span>
        </span>
        <span
          aria-hidden
          className="shrink-0 font-mono text-sm text-ink-soft transition-transform group-hover:translate-x-0.5"
        >
          →
        </span>
      </Link>
      {canFile && <MarkAppliedButton jobId={job.id} applied={false} />}
      <span
        className={`shrink-0 rounded px-2 py-0.5 font-mono text-[10px] tracking-[0.15em] uppercase ${s.cls}`}
      >
        {s.label}
      </span>
    </li>
  )
}
