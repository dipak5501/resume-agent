import type { ReactNode } from 'react'
import { motion } from 'motion/react'
import { Link } from 'react-router-dom'

import { MarkAppliedButton } from '@/components/MarkAppliedButton'
import { EmptyState } from '@/components/states/EmptyState'
import { InlineError } from '@/components/states/InlineError'
import { ListSkeleton } from '@/components/states/ListSkeleton'
import { SectionHeading } from '@/components/ui/SectionHeading'
import { Sheet } from '@/components/ui/Sheet'
import { useApplications, useSetApplicationStatus, useSetAutoApply } from '@/hooks/useJobs'
import { useProfile } from '@/hooks/useProfile'
import { applicationPdfUrl, applicationTexUrl } from '@/lib/api'
import { rise, stagger, useEntrance } from '@/lib/motion'
import type { Application, AppStatus } from '@/lib/types'

const LATER: AppStatus[] = ['applied', 'interviewing', 'offer', 'rejected', 'archived']

function filedOn(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export function Track() {
  const filed = useApplications('filed')
  const saved = useApplications('saved')
  const profile = useProfile()
  const toggle = useSetAutoApply()
  const entrance = useEntrance()
  const autoOn = Boolean(profile.data?.auto_apply)

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto max-w-4xl space-y-8 px-6 py-16 lg:py-20"
    >
      <motion.div variants={rise}>
        <SectionHeading kicker="set up & track" title={<>Applications<span className="text-marigold">.</span></>}>
          Saved runs stay separate from ones you have filed. The résumé you used stays attached.
        </SectionHeading>
      </motion.div>

      <motion.div variants={rise}>
        <Sheet className="flex flex-wrap items-center justify-between gap-4 px-4 py-3.5">
          <div>
            <p className="font-mono text-[11px] tracking-[0.18em] text-ink uppercase">Auto-apply</p>
            <p className="mt-1 max-w-lg text-sm text-ink-soft">
              Off until you turn it on. Then one finished run with an apply link can be filled and submitted. It does not apply to a list.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={autoOn}
            disabled={toggle.isPending || !profile.data}
            onClick={() => toggle.mutate(!autoOn)}
            className={`shrink-0 rounded-md border px-3 py-2 font-mono text-[11px] tracking-[0.14em] uppercase ${
              autoOn ? 'border-marigold bg-marigold/20 text-ink' : 'border-ink/15 text-ink-soft'
            }`}
          >
            {autoOn ? 'On' : 'Off'}
          </button>
        </Sheet>
      </motion.div>

      <ListBlock
        title="Saved, not applied"
        query={saved}
        empty="Nothing saved yet. Tailor a résumé and it lands here until you log it as applied."
        render={(app) => <SavedRow key={app.job_id} app={app} />}
      />

      <ListBlock
        title="Applied"
        query={filed}
        empty="Nothing filed yet. On a saved run, choose I applied; log it — or auto-apply one job from its proof."
        render={(app) => <FiledRow key={app.job_id} app={app} />}
      />
    </motion.div>
  )
}

function ListBlock({
  title,
  query,
  empty,
  render,
}: {
  title: string
  query: ReturnType<typeof useApplications>
  empty: string
  render: (app: Application) => ReactNode
}) {
  return (
    <motion.div variants={rise} className="space-y-3">
      <h2 className="font-mono text-[11px] tracking-[0.22em] text-cream-soft uppercase">{title}</h2>
      {query.isPending && <ListSkeleton />}
      {query.isError && (
        <InlineError onRetry={() => query.refetch()}>
          Couldn&rsquo;t load this list — is the backend running?
        </InlineError>
      )}
      {query.data && query.data.length === 0 && <EmptyState title="Nothing here yet.">{empty}</EmptyState>}
      {query.data && query.data.length > 0 && (
        <Sheet as="ul" sm className="divide-y divide-border overflow-hidden">
          {query.data.map(render)}
        </Sheet>
      )}
    </motion.div>
  )
}

function ResumeLinks({ app }: { app: Application }) {
  if (!app.has_pdf) return null
  const pdf = applicationPdfUrl(app.job_id)
  return (
    <span className="flex shrink-0 items-center gap-3 font-mono text-[11px] tracking-[0.12em] uppercase">
      <a href={pdf} target="_blank" rel="noopener noreferrer" className="text-ink underline-offset-2 hover:underline">Open</a>
      <a href={pdf} download="resume.pdf" className="text-ink underline-offset-2 hover:underline">Download</a>
      {app.has_tex && (
        <a href={applicationTexUrl(app.job_id)} download="resume.tex" className="text-ink-soft underline-offset-2 hover:underline">.tex</a>
      )}
    </span>
  )
}

function SavedRow({ app }: { app: Application }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-sm text-ink">{app.title}</span>
        <span className="font-mono text-[11px] text-ink-soft">
          {app.company ? `${app.company} · ` : ''}
          saved {filedOn(app.saved_at)}
          {app.resume_label ? ` · ${app.resume_label}` : ''}
        </span>
      </span>
      <StatusBadge status={app.status} />
      <Link to={`/tailor/${app.job_id}`} className="shrink-0 font-mono text-[11px] tracking-[0.12em] text-ink uppercase underline-offset-2 hover:underline">
        Prepare
      </Link>
      {app.status === 'ready' && <MarkAppliedButton jobId={app.job_id} applied={false} />}
      <ResumeLinks app={app} />
    </li>
  )
}

function FiledRow({ app }: { app: Application }) {
  const update = useSetApplicationStatus()
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3.5">
      <span className="min-w-0 flex-1">
        <span className="block truncate font-mono text-sm text-ink">{app.title}</span>
        <span className="font-mono text-[11px] text-ink-soft">
          {app.company ? `${app.company} · ` : ''}
          {app.applied_at ? filedOn(app.applied_at) : filedOn(app.saved_at)}
          {app.resume_label ? ` · ${app.resume_label}` : ''}
        </span>
      </span>
      <label className="sr-only" htmlFor={`status-${app.job_id}`}>Status</label>
      <select
        id={`status-${app.job_id}`}
        value={app.status}
        onChange={(e) => update.mutate({ id: app.job_id, status: e.target.value as AppStatus })}
        className="shrink-0 rounded border border-ink/15 bg-transparent px-2 py-1 font-mono text-[10px] tracking-[0.12em] text-ink uppercase"
      >
        {LATER.map((status) => (
          <option key={status} value={status}>{status}</option>
        ))}
      </select>
      <Link to={`/tailor/${app.job_id}`} className="shrink-0 font-mono text-[11px] tracking-[0.12em] text-ink uppercase underline-offset-2 hover:underline">
        Prepare
      </Link>
      <ResumeLinks app={app} />
    </li>
  )
}

function StatusBadge({ status }: { status: string }) {
  return (
    <span className="shrink-0 rounded bg-marigold/20 px-2 py-0.5 font-mono text-[10px] tracking-[0.15em] text-marigold uppercase">
      {status}
    </span>
  )
}
