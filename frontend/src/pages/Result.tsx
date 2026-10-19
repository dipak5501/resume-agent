import { motion } from 'motion/react'
import { Link } from 'react-router-dom'

import { ApplicationCard } from '@/components/ApplicationCard'
import { AutoApplyButton } from '@/components/AutoApplyButton'
import { FitNoteCard } from '@/components/FitNoteCard'
import { ResumeChat } from '@/components/ResumeChat'
import { MarkAppliedButton } from '@/components/MarkAppliedButton'
import { HiringAgentCard } from '@/components/HiringAgentCard'
import { KeywordMarks } from '@/components/KeywordMarks'
import { RequirementChecks } from '@/components/RequirementChecks'
import { RevisionLog } from '@/components/RevisionLog'
import { ScoreReveal } from '@/components/ScoreReveal'
import { Button } from '@/components/ui/button'
import { Kicker } from '@/components/ui/Kicker'
import { Mark } from '@/components/ui/Mark'
import { Sheet } from '@/components/ui/Sheet'
import { Stamp } from '@/components/ui/Stamp'
import { useSaveLocal } from '@/hooks/useJobs'
import { downloadTex, pdfUrl } from '@/lib/api'
import { rise, stagger, useEntrance } from '@/lib/motion'
import type { JobAnswer, PipelineResult, RoundEntry } from '@/lib/types'

export function Result({
  jobId,
  round,
  rounds,
  answers,
  result,
  applyUrl,
  applied,
  onStartOver,
}: {
  jobId: string
  round: number
  rounds: RoundEntry[]
  answers: JobAnswer[]
  result: PipelineResult
  applyUrl: string | null
  applied: boolean
  onStartOver: () => void
}) {
  const { report } = result
  // The original was kept: no rewrite scored higher or none fit one page (T33 made this common)
  const untouched = report.changes.length === 0 && report.added.length === 0
  const fromPdf = result.kind === 'pdf'
  const entrance = useEntrance()
  const save = useSaveLocal()

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      exit={{ opacity: 0, transition: { duration: 0.2 } }}
      className="mx-auto max-w-[96rem] px-6 py-14 lg:py-20"
    >
      <motion.header variants={rise} className="mb-10 flex items-end justify-between gap-6">
        <div>
          <Kicker>proof approved</Kicker>
          <h1 className="mt-3 font-serif text-5xl leading-[0.95] tracking-[-0.02em] text-cream sm:text-6xl lg:text-7xl">
            {untouched ? 'Your résumé, kept as is' : 'Your tailored résumé'}
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-cream-soft">
            {untouched
              ? fromPdf
                ? 'No rewrite improved on the text of your PDF, so that wording is what we laid out on one page.'
                : 'No rewrite improved on your original for this role, so it goes unchanged. The note under Proof rounds says why.'
              : fromPdf
                ? 'Rewritten from your PDF onto one page, using only employers, skills, and numbers already in it.'
                : 'Tailored to the role and compiled to one page. Review what we added below — every claim is yours to stand behind.'}
          </p>
        </div>
        <button
          onClick={onStartOver}
          className="shrink-0 pb-2 font-mono text-xs tracking-[0.2em] text-cream-soft uppercase underline-offset-4 transition hover:text-cream hover:underline"
        >
          new brief →
        </button>
      </motion.header>

      {report.selection_warning && (
        <Sheet
          as={motion.div}
          sm
          variants={rise}
          role="alert"
          className="mb-10 border-l-[3px] border-l-gap px-5 py-3.5 text-ink"
        >
          <span className="font-mono text-xs tracking-[0.2em] text-gap uppercase">note · </span>
          {report.selection_warning}
        </Sheet>
      )}

      <div className="grid grid-cols-1 gap-10 lg:grid-cols-[1.12fr_0.88fr]">
        {/* Left: the proofed page itself — a physical sheet on the desk, stamped. */}
        <motion.div variants={rise} className="lg:sticky lg:top-8 lg:self-start">
          <div className="relative">
            <Stamp className="absolute -top-6 -right-5 z-10" sub={<>one page · {new Date().getFullYear()}</>} />
            <Sheet className="overflow-hidden p-2.5">
              <iframe
                title="Tailored résumé (PDF)"
                src={`${pdfUrl(jobId)}?r=${round}`}
                className="h-[80vh] w-full rounded-sm bg-white"
              />
            </Sheet>
          </div>
          <div className="mt-5 flex gap-3">
            <a
              href={pdfUrl(jobId)}
              download="resume.pdf"
              className="inline-flex h-12 flex-1 items-center justify-center rounded-md bg-marigold font-mono text-sm tracking-[0.18em] text-ink uppercase shadow-[0_10px_28px_-12px_rgba(243,180,31,0.7)] transition hover:brightness-95 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-desk focus-visible:outline-none"
            >
              Download PDF
            </a>
            {!fromPdf && (
              <Button
                variant="outline"
                onClick={() => downloadTex(result.tex)}
                className="h-12 flex-1 rounded-md border-cream/25 bg-transparent font-mono text-sm tracking-[0.18em] text-cream uppercase hover:bg-cream/10 hover:text-cream"
              >
                Download .tex
              </Button>
            )}
          </div>

          <MarkAppliedButton jobId={jobId} applied={applied} tone="desk" block />
          <AutoApplyButton jobId={jobId} applyUrl={applyUrl} applied={applied} />
          {applied && (
            <Link
              to="/track"
              className="mt-2 block text-center font-mono text-[11px] tracking-[0.12em] text-cream-soft uppercase underline-offset-4 hover:text-cream hover:underline"
            >
              Set up &amp; track →
            </Link>
          )}

          {/* Save locally (local-dev): file the PDF into tailored-resume/<company>/…
              and log it in the tracker CSV. Does not touch the browser download. */}
          <button
            onClick={() => save.mutate(jobId)}
            disabled={save.isPending}
            className="mt-3 w-full rounded-md border border-dashed border-cream-soft/25 px-5 py-2.5 font-mono text-xs tracking-[0.15em] text-cream-soft uppercase transition hover:border-marigold/40 hover:text-cream disabled:opacity-40"
          >
            {save.isPending ? 'filing to the desk…' : 'Save locally'}
          </button>
          {save.isSuccess && (
            <p className="mt-2 font-mono text-[11px] text-cream-soft">
              saved → <span className="text-marigold">{save.data.saved_path}</span>
            </p>
          )}
          {save.isError && (
            <p role="alert" className="mt-2 font-mono text-[11px] text-gap-hi">
              {(save.error as Error).message}
            </p>
          )}

          {/* T16: close the loop — carry this résumé straight to the posting's
              apply form, where the installed extension lights up and fills it.
              Only link-JD runs have an apply URL; pasted runs get the hint. */}
          {applyUrl ? (
            <a
              href={applyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="group mt-3 flex items-center justify-between gap-4 rounded-md border border-marigold/50 bg-marigold/10 px-5 py-3.5 transition hover:bg-marigold/15 focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-desk focus-visible:outline-none"
            >
              <span className="flex flex-col">
                <span className="font-mono text-[10px] tracking-[0.26em] text-marigold uppercase">
                  next · apply
                </span>
                <span className="font-serif text-lg text-cream">Apply with this résumé</span>
              </span>
              <span
                aria-hidden
                className="font-mono text-xl text-marigold transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5"
              >
                ↗
              </span>
            </a>
          ) : (
            <p className="mt-3 rounded-md border border-dashed border-cream-soft/20 px-5 py-3 text-center font-mono text-[11px] leading-relaxed tracking-[0.02em] text-cream-soft">
              Start from a job <span className="text-cream-soft">link</span> on the desk to enable
              one-click apply here.
            </p>
          )}
        </motion.div>

        {/* Right: the marks — scores, coverage, what we added, revisions. */}
        <div className="space-y-8">
          <motion.div variants={rise}>
            <ScoreReveal before={report.ats_before.overall} after={report.ats_after.overall} />
          </motion.div>

          <FitNoteCard jobId={jobId} />

          {report.ats_after.requirements.length > 0 && (
            <Sheet as={motion.section} variants={rise} className="p-7">
              <h2 className="mb-5 font-serif text-2xl text-ink">Requirements</h2>
              <RequirementChecks requirements={report.ats_after.requirements} />
            </Sheet>
          )}

          <Sheet as={motion.section} variants={rise} className="p-7">
            <h2 className="mb-5 font-serif text-2xl text-ink">Keyword coverage</h2>
            <KeywordMarks matched={report.ats_after.matched} missing={report.ats_after.missing} />
          </Sheet>

          {report.added.length > 0 && (
            <Sheet as={motion.section} variants={rise} className="border-l-[3px] border-l-marigold p-7">
              <h2 className="font-serif text-2xl text-ink">Added — review these</h2>
              <p className="mt-1.5 mb-4 text-sm leading-relaxed text-ink-soft">
                We wrote these in to hit the match. They&rsquo;re now claims on your résumé &mdash;
                make sure you can speak to each one in an interview.
              </p>
              <div className="flex flex-wrap gap-x-1.5 gap-y-2.5 text-lg">
                {report.added.map((a) => (
                  <Mark key={a}>{a}</Mark>
                ))}
              </div>
            </Sheet>
          )}

          {report.hiring_agent && (
            <motion.div variants={rise}>
              <HiringAgentCard report={report.hiring_agent} />
            </motion.div>
          )}

          {/* The round history sits directly above the card, so asking for a
              revision and watching a new slip land on the log is a single motion. */}
          <RevisionLog rounds={rounds} warnings={report.warnings} />

          <ApplicationCard jobId={jobId} round={round} answers={answers} />
          <ResumeChat jobId={jobId} />
        </div>
      </div>
    </motion.div>
  )
}
