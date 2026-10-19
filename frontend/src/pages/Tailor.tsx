import { AnimatePresence, useReducedMotion } from 'motion/react'
import { useNavigate, useParams } from 'react-router-dom'

import { ErrorState } from '@/components/states/ErrorState'
import { Loading } from '@/components/states/Loading'
import { useJob } from '@/hooks/useJobs'
import { Result } from './Result'
import { Run } from './Run'

// The /tailor/:jobId route (T14). The run id lives in the PATH, so a reload or a
// shared link resumes the exact run — the migration invariant from the old
// ?job=… state. Drives Run → Result off the polled job status.
export function Tailor() {
  const { jobId } = useParams<{ jobId: string }>()
  const navigate = useNavigate()
  const { data: job, isError } = useJob(jobId ?? null)
  const startOver = () => navigate('/')
  const reduced = useReducedMotion()

  if (!jobId || isError) {
    return (
      <ErrorState
        kicker="off the desk"
        title={<>That run isn&rsquo;t here</>}
        action={{ label: 'New brief', onClick: startOver }}
      >
        It may have expired. Start a fresh brief.
      </ErrorState>
    )
  }

  if (!job) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-32 text-center">
        <Loading className="tracking-[0.3em]">loading the desk…</Loading>
      </div>
    )
  }

  const view =
    job.status === 'done' && job.result ? (
      <Result
        key="result"
        jobId={job.id}
        round={job.round}
        rounds={job.rounds}
        answers={job.answers}
        result={job.result}
        applyUrl={job.apply_url}
        applied={job.applied}
        onStartOver={startOver}
      />
    ) : (
      <Run key="run" job={job} onStartOver={startOver} />
    )

  // Run → Result reveal: the progress view fades out and the proof reveals in
  // (its own sections then stagger onto the desk). Same route, so this — not the
  // AppShell page transition — owns the moment. Reduced motion: swap instantly.
  // initial={false}: a cold reload straight onto a finished /tailor/:id shows the
  // proof immediately (no entrance replay); only the live run→done swap animates.
  return reduced ? view : <AnimatePresence mode="wait" initial={false}>{view}</AnimatePresence>
}
