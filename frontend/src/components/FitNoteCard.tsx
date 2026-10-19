import { motion } from 'motion/react'

import { Sheet } from '@/components/ui/Sheet'
import { useFitNote } from '@/hooks/useJobs'
import { rise } from '@/lib/motion'

const CONSTRAINT = 'Do not invent skills, titles, or numbers that are not in the résumé.'

export function FitNoteCard({ jobId }: { jobId: string }) {
  const note = useFitNote(jobId)
  return (
    <Sheet as={motion.section} variants={rise} className="p-7">
      <h2 className="font-serif text-2xl text-ink">Fit for this job</h2>
      <p className="mt-2 text-sm leading-relaxed text-ink-soft">{note.data?.constraint ?? CONSTRAINT}</p>
      {note.isPending && <p className="mt-4 font-mono text-xs text-ink-soft">Reading the résumé…</p>}
      {note.isError && (
        <p className="mt-4 font-mono text-xs text-ink-soft">Couldn&rsquo;t write a fit note. {CONSTRAINT}</p>
      )}
      {note.data && (
        <div className="mt-5 grid gap-5 sm:grid-cols-2">
          <div>
            <h3 className="font-mono text-[10px] tracking-[0.18em] text-ink-soft uppercase">Matches</h3>
            <ul className="mt-2 space-y-1.5 text-sm text-ink">
              {note.data.matches.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
          <div>
            <h3 className="font-mono text-[10px] tracking-[0.18em] text-ink-soft uppercase">Thin</h3>
            <ul className="mt-2 space-y-1.5 text-sm text-ink">
              {note.data.thin.map((item) => <li key={item}>{item}</li>)}
            </ul>
          </div>
        </div>
      )}
    </Sheet>
  )
}
