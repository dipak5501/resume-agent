import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useFeedback } from '@/hooks/useJobs'
import { OUTER_LOOP_MAX } from '@/lib/types'

// The revise mode of the application card (T22, re-housed by T24). Renders bare:
// the card owns the sheet and names the mode, so there is no heading here.
export function FeedbackBox({ jobId, round }: { jobId: string; round: number }) {
  const [text, setText] = useState('')
  const feedback = useFeedback(jobId)
  const left = OUTER_LOOP_MAX - round
  const atCap = left <= 0

  if (atCap) {
    return (
      <p className="mt-5 font-mono text-sm text-ink-soft">
        You&rsquo;ve used all {OUTER_LOOP_MAX} revision rounds. Start over for a fresh run.
      </p>
    )
  }

  return (
    <>
      <p className="mt-5 font-mono text-[11px] tracking-[0.15em] text-ink-soft uppercase">
        {left} round{left === 1 ? '' : 's'} left
      </p>
      <label htmlFor="feedback" className="sr-only">
        Revision request
      </label>
      <Textarea
        id="feedback"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="e.g. lead with the platform work; tone down the AI/ML framing…"
        className="mt-3 min-h-24 resize-y border-ink/20 bg-paper text-ink focus-visible:ring-marigold"
      />
      {feedback.isError && (
        <p role="alert" className="mt-2 font-mono text-sm text-gap">
          {(feedback.error as Error).message}
        </p>
      )}
      <Button
        onClick={() => feedback.mutate(text, { onSuccess: () => setText('') })}
        disabled={text.trim().length < 4 || feedback.isPending}
        className="mt-4 h-11 rounded-md bg-marigold px-6 font-mono text-sm tracking-[0.18em] text-ink uppercase transition hover:brightness-95 disabled:opacity-40"
      >
        {feedback.isPending ? 'sending…' : 'Revise'}
      </Button>
    </>
  )
}
