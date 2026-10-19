import { useState } from 'react'
import { motion } from 'motion/react'

import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { useCreateAnswer } from '@/hooks/useAnswers'
import { useAnswerQuestion } from '@/hooks/useJobs'
import type { JobAnswer } from '@/lib/types'

// The answer mode of the application card (T24). Drafts an answer to a real
// application question grounded on THIS run's tailored résumé, then files it on
// the run's answers log — reply slips carboned onto the desk, so a multi-question
// application can be copied across in one sitting.
//
// Copy-paste only, by design: this is the honest counterpart to the extension for
// portals we can't (or shouldn't) autofill. Nothing here is ever submitted.

/** Where the words came from — always shown, never buried. */
const PROVENANCE: Record<JobAnswer['source'], string> = {
  bank_verbatim: 'from your answer bank, unchanged',
  bank_adapted: 'your saved answer, re-grounded on this résumé',
  llm_fresh: 'drafted from this résumé',
  blank: 'left blank',
}

function CopyButton({ text, label = 'copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      onClick={() => {
        navigator.clipboard.writeText(text).then(
          () => (setDone(true), setTimeout(() => setDone(false), 1600)),
          () => undefined, // a blocked clipboard is not worth an error state
        )
      }}
      className="shrink-0 rounded-sm border border-ink/15 px-2.5 py-1 font-mono text-[10px] tracking-[0.18em] text-ink-soft uppercase transition hover:border-marigold hover:text-ink"
    >
      {done ? '✓ copied' : label}
    </button>
  )
}

/** Every draft is machine-written and yours to stand behind — say so, always. */
function ReviewChip() {
  return (
    <span className="rounded-sm bg-highlight px-1.5 py-0.5 font-mono text-[10px] tracking-[0.14em] text-ink uppercase">
      review
    </span>
  )
}

export function ApplicationAnswers({ jobId, answers }: { jobId: string; answers: JobAnswer[] }) {
  const [question, setQuestion] = useState('')
  const [draft, setDraft] = useState<JobAnswer | null>(null)
  const [text, setText] = useState('') // the draft, editable before you copy it
  const ask = useAnswerQuestion(jobId)
  const save = useCreateAnswer()

  // The active draft is already the newest entry on the server's log; show it
  // once, in its editable form, and let the log hold everything before it.
  const filed = answers.filter((a) => a.created_at !== draft?.created_at)

  function submit() {
    if (question.trim().length < 4 || ask.isPending) return
    ask.mutate(question, {
      onSuccess: (res) => {
        setDraft(res)
        setText(res.answer)
        setQuestion('')
        save.reset() // one save mutation per card — a new draft is not yet banked
      },
    })
  }

  return (
    <>
      <p className="mt-5 font-mono text-[11px] leading-relaxed text-ink-soft">
        answering never costs a revision round.
      </p>

      <label htmlFor="question" className="sr-only">
        Application question
      </label>
      <Textarea
        id="question"
        value={question}
        onChange={(e) => setQuestion(e.target.value)}
        placeholder="e.g. Why do you think you're a fit for this role?"
        className="mt-3 min-h-20 resize-y border-ink/20 bg-paper text-ink focus-visible:ring-marigold"
      />
      {ask.isError && (
        <p role="alert" className="mt-2 font-mono text-sm text-gap">
          {(ask.error as Error).message}
        </p>
      )}
      <Button
        onClick={submit}
        disabled={question.trim().length < 4 || ask.isPending}
        className="mt-4 h-11 rounded-md bg-marigold px-6 font-mono text-sm tracking-[0.18em] text-ink uppercase transition hover:brightness-95 disabled:opacity-40"
      >
        {ask.isPending ? 'drafting…' : 'Draft answer'}
      </Button>

      {/* the fresh draft — editable, stamped with where it came from */}
      {draft && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
          className="mt-7 border-t border-dashed border-paper-line pt-6"
        >
          <p className="font-mono text-[11px] leading-relaxed tracking-[0.06em] text-ink-soft">
            <span className="text-marigold">Q.</span> {draft.question}
          </p>

          {draft.answer ? (
            <>
              <label htmlFor="draft" className="sr-only">
                Drafted answer
              </label>
              <Textarea
                id="draft"
                value={text}
                onChange={(e) => setText(e.target.value)}
                className="mt-3 min-h-32 resize-y border-ink/20 bg-paper font-serif text-[0.95rem] leading-relaxed text-ink focus-visible:ring-marigold"
              />
              <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2">
                <span className="font-mono text-[10px] tracking-[0.14em] text-ink-soft uppercase">
                  {PROVENANCE[draft.source]}
                </span>
                {draft.needs_review && <ReviewChip />}
                <span className="ml-auto flex items-center gap-2">
                  <CopyButton text={text} label="copy answer" />
                  <button
                    onClick={() =>
                      save.mutate({ question: draft.question, answer: text, mode: draft.save_mode })
                    }
                    disabled={!text.trim() || save.isPending}
                    className="shrink-0 rounded-sm border border-dashed border-ink/20 px-2.5 py-1 font-mono text-[10px] tracking-[0.18em] text-ink-soft uppercase transition hover:border-marigold hover:text-ink disabled:opacity-40"
                  >
                    {save.isSuccess ? '✓ in your bank' : save.isPending ? 'saving…' : 'save to bank'}
                  </button>
                </span>
              </div>
              {save.isSuccess && (
                <p className="mt-2 font-mono text-[10px] leading-relaxed text-ink-soft">
                  {draft.save_mode === 'verbatim'
                    ? 'saved as a fact — reused word for word on your next application.'
                    : 'saved as a template — re-grounded on each new job’s tailored résumé, so it never claims something that résumé doesn’t say.'}
                </p>
              )}
            </>
          ) : (
            // Honest empty state: we would have had to invent something, so we
            // didn't. The backend's reason says which line the answer crossed.
            <div className="mt-3 border-l-[3px] border-l-gap bg-gap/5 px-4 py-3">
              <p className="font-mono text-[11px] tracking-[0.14em] text-gap uppercase">
                nothing drafted
              </p>
              <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">
                {draft.reason ?? 'fill this one yourself.'}
              </p>
            </div>
          )}
        </motion.div>
      )}

      {/* the run's answers log — every question you've asked for this job */}
      {filed.length > 0 && (
        <section className="mt-8 border-t border-paper-line pt-6">
          <header className="flex items-baseline justify-between gap-4">
            <h3 className="font-serif text-lg text-ink">Answers for this application</h3>
            <span className="font-mono text-[11px] tracking-[0.15em] text-ink-soft uppercase">
              {filed.length} answered
            </span>
          </header>

          <ol className="mt-4">
            {filed
              .slice()
              .reverse()
              .map((a, i) => (
                <li
                  key={a.created_at + a.question}
                  className={i === 0 ? '' : 'mt-5 border-t border-dashed border-paper-line pt-5'}
                >
                  <div className="flex items-start justify-between gap-3">
                    <p className="font-mono text-[11px] leading-relaxed tracking-[0.06em] text-ink-soft">
                      <span className="text-marigold">Q.</span> {a.question}
                    </p>
                    {a.answer && <CopyButton text={a.answer} />}
                  </div>
                  {/* a blank never wears the same rule as a real answer — at a
                      glance the log must show what you still have to write */}
                  <p
                    className={
                      a.answer
                        ? 'mt-2 border-l-2 border-marigold/50 pl-3 font-serif text-[0.95rem] leading-relaxed whitespace-pre-wrap text-ink'
                        : 'mt-2 border-l-2 border-gap/50 pl-3 font-serif text-[0.95rem] leading-relaxed text-ink-soft italic'
                    }
                  >
                    {a.answer || (a.reason ?? 'left blank — fill this one yourself.')}
                  </p>
                  <p className="mt-2 flex flex-wrap items-center gap-2 font-mono text-[10px] tracking-[0.14em] text-ink-soft uppercase">
                    {PROVENANCE[a.source]}
                    {a.needs_review && <ReviewChip />}
                  </p>
                </li>
              ))}
          </ol>
        </section>
      )}
    </>
  )
}
