import { Fragment, useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { motion } from 'motion/react'

import { Dropzone } from '@/components/Dropzone'
import { ListSkeleton } from '@/components/states/ListSkeleton'
import { Button } from '@/components/ui/button'
import { Kicker } from '@/components/ui/Kicker'
import { Mark } from '@/components/ui/Mark'
import { Sheet } from '@/components/ui/Sheet'
import { Textarea } from '@/components/ui/textarea'
import { useCreateJob, useJdFromUrl, useJdHandoff } from '@/hooks/useJobs'
import { ApiError } from '@/lib/api'
import { useResumes, useUploadResume } from '@/hooks/useProfile'
import { markTailored, useCanTailor } from '@/hooks/useSetup'
import { isPdfFile } from '@/lib/resume'
import { rise, stagger, useEntrance } from '@/lib/motion'
import type { JdScreen, JdSource } from '@/lib/types'
import { MAX_AGE_MS, cn, postingTime } from '@/lib/utils'

function Eyebrow({ n, children }: { n: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-2.5 font-mono text-[11px] tracking-[0.22em] uppercase">
      <span className="text-marigold">{n}</span>
      <span className="text-cream-soft">{children}</span>
    </div>
  )
}

const DAY_MS = 24 * 60 * 60 * 1000
const ago = new Intl.RelativeTimeFormat('en', { numeric: 'auto' })
const dayFmt = new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric' })

// A bare "YYYY-MM-DD" (Workday) is a calendar day, so read it as a LOCAL day;
// as UTC midnight it would show as the previous day across the Americas.
function postedDate(iso: string): Date {
  const day = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso)
  return day ? new Date(+day[1], +day[2] - 1, +day[3]) : new Date(postingTime(iso))
}

// Calendar days between two local dates; rounding absorbs a DST 23/25h day.
const daysBetween = (a: Date, b: Date) =>
  Math.round((new Date(b).setHours(0, 0, 0, 0) - new Date(a).setHours(0, 0, 0, 0)) / DAY_MS)

/** T28: how fresh the fetched posting is, and whether its company joined the Board. */
function Freshness({ source }: { source: JdSource }) {
  const [now] = useState(() => new Date()) // as of this fetch; remounted per link
  const posted = source.posted_at ? postedDate(source.posted_at) : null
  const updated = source.updated_at ? dayFmt.format(postedDate(source.updated_at)) : null
  const board = { added: 'company added to Board', tracked: 'company already on Board' }
  // each phrase is one unit, so a narrow screen breaks between them, never inside
  const parts = [
    posted === null ? (
      'posting date not provided by this site'
    ) : (
      <>
        posted {dayFmt.format(posted)}{' '}
        <span className={cn(now.getTime() - posted.getTime() > MAX_AGE_MS && 'text-gap-hi')}>
          ({ago.format(-daysBetween(posted, now), 'day')})
        </span>
      </>
    ),
    // same-day "updated" is just the posting itself; say it only when it adds news
    updated && updated !== (posted && dayFmt.format(posted)) && `updated ${updated}`,
    source.board && board[source.board],
  ].filter(Boolean)
  return (
    <p className="font-mono text-xs text-cream-soft">
      {parts.map((part, i) => (
        <Fragment key={i}>
          {i > 0 && ' · '}
          <span className="whitespace-nowrap">{part}</span>
        </Fragment>
      ))}
    </p>
  )
}

const SCREEN_ROWS = [
  ['experience', 'experience'],
  ['citizenship', 'US citizen'],
  ['no_sponsorship', 'sponsorship'],
  ['clearance', 'clearance'],
] as const

/** T39: the posting's deal-breakers, each shown as the sentence that says it. */
function Screening({ screen }: { screen: JdScreen }) {
  return (
    <section aria-label="Screening" className="space-y-2 border-l-2 border-marigold/60 py-1 pl-3">
      <p className="font-mono text-[11px] tracking-[0.22em] text-cream-soft uppercase">screening · from the fetched JD</p>
      <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 font-mono text-xs leading-relaxed">
        {SCREEN_ROWS.map(([key, label]) => {
          const [first, ...more] = screen[key]
          return (
            <Fragment key={key}>
              <dt className="text-cream-soft">{label}</dt>
              <dd className="min-w-0 wrap-break-word">
                {/* RTX quotes a 94-char eCFR URL: break it rather than overflow */}
                {first === undefined ? (
                  // "Several years of experience" states no number
                  <span className="text-cream-soft/70">{key === 'experience' ? 'no minimum stated' : 'not mentioned'}</span>
                ) : (
                  // one line each, so the JD keeps the room; open a row to read every quote in full
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-baseline gap-2 [&::-webkit-details-marker]:hidden">
                      {key === 'experience' && screen.min_years !== null && (
                        <span className="shrink-0 text-marigold">
                          min {screen.min_years} {screen.min_years === 1 ? 'yr' : 'yrs'}
                        </span>
                      )}
                      <span className="min-w-0 truncate group-open:whitespace-normal">
                        <Mark className="text-ink">{first}</Mark>
                      </span>
                      {more.length > 0 && <span className="shrink-0 text-cream-soft group-open:hidden">+{more.length}</span>}
                    </summary>
                    {more.length > 0 && (
                      <ul className="mt-1.5 space-y-1.5">
                        {more.map((quote) => (
                          <li key={quote}>
                            <Mark className="text-ink">{quote}</Mark>
                          </li>
                        ))}
                      </ul>
                    )}
                  </details>
                )}
              </dd>
            </Fragment>
          )
        })}
      </dl>
    </section>
  )
}

// The working screen (T21): on a real desk (`desk:` — wide and tall enough) this
// fills the viewport exactly and never scrolls the page. The brief and the
// sources scroll *inside* their columns, so the Tailor button stays in view no
// matter how long the JD is. Anything smaller falls back to natural scroll.
export function Compose() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const initialUrl = params.get('url') || ''
  const [draft, setJd] = useState<string | null>(null)
  const [link, setLink] = useState(initialUrl)
  const [files, setFiles] = useState<File[]>([])
  const [selectedIds, setSelectedIds] = useState<string[] | null>(null) // null = not yet seeded
  const create = useCreateJob()
  const upload = useUploadResume()
  const jdFetch = useJdFromUrl()
  const fromBoard = params.get('from') === 'board'
  const handoff = useJdHandoff(initialUrl, fromBoard)
  const source = jdFetch.data ?? handoff.data
  // Only a pristine field follows the automatic result. Even an intentional
  // edit to an empty string must survive a slow fetch or a retry.
  const jd = draft ?? source?.text ?? ''
  const unavailable = handoff.error instanceof ApiError && [404, 410].includes(handoff.error.status)

  const { data: resumes = [], isPending: resumesLoading } = useResumes()
  const entrance = useEntrance()

  // pre-check the whole library once (the selector picks the JD-closest across
  // all of them), without clobbering user edits
  useEffect(() => {
    if (selectedIds === null && resumes.length > 0) {
      // one-shot seed: every saved résumé, PDF or .tex, is a tailoring source.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelectedIds(resumes.map((r) => r.id))
    }
  }, [resumes, selectedIds])

  const selected = selectedIds ?? []
  const toggle = (id: string) =>
    setSelectedIds((s) => {
      const cur = s ?? []
      return cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id]
    })

  const pdfFiles = files.filter((f) => isPdfFile(f.name))
  const busy = create.isPending || upload.isPending || handoff.isFetching
  // A dropped file is this run's source. A PDF is also saved so it can fill
  // blank profile fields and be picked again from the library.
  const tailorGate = useCanTailor()
  const setupReady = tailorGate === true
  const sourcesReady = jd.trim().length > 20 && (files.length > 0 || (files.length === 0 && selected.length > 0)) && !busy
  const canTailor = sourcesReady && setupReady

  async function submit() {
    if (!canTailor) return
    if (pdfFiles.length) {
      try {
        for (const file of pdfFiles) await upload.mutateAsync({ file })
      } catch {
        return
      }
    }
    // T16: carry the adapter's apply URL (only set when the JD came from a link)
    // so the Result page can offer one-click "Apply with this résumé".
    const applyUrl = source?.apply_url ?? null
    const title = source?.title ?? null // T32: Ashby JD text never names the role
    const company = source?.company ?? null
    const payload = files.length > 0 ? { jd, files, applyUrl, title, company } : { jd, resumeIds: selected, applyUrl, title, company }
    create.mutate(payload, {
      onSuccess: (r) => {
        markTailored() // outlives the in-memory job list, so setup stays "done"
        navigate(`/tailor/${r.job_id}`)
      },
    })
  }

  function fetchLink() {
    const u = link.trim()
    if (!u || jdFetch.isPending) return
    jdFetch.mutate(u, { onSuccess: (src) => setJd(src.text) })
  }

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto flex max-w-[96rem] flex-col gap-9 px-6 py-12 desk:h-full desk:gap-7 desk:overflow-hidden desk:py-8"
    >
      {/* the masthead: title left, the deck alongside it — a slim working header,
          not a landing hero, so the desk itself is above the fold */}
      <motion.header
        variants={rise}
        className="flex shrink-0 flex-wrap items-end justify-between gap-x-14 gap-y-4 border-b border-desk-line pb-6"
      >
        <div>
          <Kicker>the proofing desk</Kicker>
          <h1 className="mt-3 font-serif text-5xl leading-[0.9] font-medium tracking-[-0.02em] text-cream sm:text-6xl">
            Set the brief<span className="text-marigold">.</span>
          </h1>
        </div>
        <p className="max-w-lg text-sm leading-relaxed text-cream-soft sm:text-right">
          Paste the job description and lay your résumé sources on the desk. We&rsquo;ll pick the
          closest one, tailor it to the role &mdash; honestly, one page &mdash; and hand back a
          proofed PDF.
        </p>
      </motion.header>

      <div className="grid grid-cols-1 gap-x-14 gap-y-12 desk:min-h-0 desk:flex-1 lg:grid-cols-[1.1fr_0.9fr]">
        <motion.div variants={rise} className="flex flex-col gap-4 desk:min-h-0">
          <label htmlFor="jd" className="block shrink-0">
            <Eyebrow n="01">the brief · job description</Eyebrow>
          </label>

          {/* paste a job link → fills the JD field (Workday · Greenhouse · Lever · Ashby, else generic) */}
          <div className="shrink-0 space-y-2">
            {initialUrl && !jdFetch.data && (
              <>
                {handoff.isFetching && (
                  <p role="status" className="font-mono text-xs text-cream-soft">
                    {fromBoard ? 'Checking this posting and fetching its description…' : 'Fetching the job description…'}
                  </p>
                )}
                {handoff.isError && (
                  <div role="alert" className="space-y-2 border-l-2 border-gap-hi pl-3 py-1">
                    <p className="font-mono text-xs text-gap-hi">{handoff.error.message}</p>
                    <div className="flex items-center gap-4 font-mono text-xs">
                      {!unavailable && (
                        <button type="button" onClick={() => void handoff.refetch()} disabled={handoff.isFetching}
                          className="text-cream underline underline-offset-4 disabled:opacity-40">Retry</button>
                      )}
                      {fromBoard && <Link to="/board" className="text-marigold underline underline-offset-4">Back to Board</Link>}
                    </div>
                  </div>
                )}
              </>
            )}
            <div className="flex gap-2">
              <input
                type="url"
                value={link}
                onChange={(e) => setLink(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && (e.preventDefault(), fetchLink())}
                placeholder="…or paste a job link (Workday · Greenhouse · Lever · Ashby)"
                className="min-w-0 flex-1 rounded-md border border-cream-soft/20 bg-transparent px-3 py-2.5 font-mono text-xs text-cream placeholder:text-cream-soft/50 focus:border-marigold focus:outline-none"
              />
              <Button
                onClick={fetchLink}
                disabled={!link.trim() || jdFetch.isPending}
                className="rounded-md bg-cream-soft/10 px-4 font-mono text-xs tracking-[0.15em] text-cream uppercase hover:bg-cream-soft/20 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {jdFetch.isPending ? 'fetching…' : 'fetch'}
              </Button>
            </div>
            {jdFetch.isError && (
              <p role="alert" className="font-mono text-xs text-gap-hi">
                {(jdFetch.error as Error).message}
              </p>
            )}
            {source && (
              <p className="font-mono text-xs text-cream-soft">
                filled from <span className="text-marigold">{source.adapter}</span>
                {source.title ? ` · ${source.title}` : ''} — review &amp; edit below before running.
              </p>
            )}
            {source && <Freshness key={source.source_url} source={source} />}
            {source?.screen && <Screening key={`screen:${source.source_url}`} screen={source.screen} />}
            {source?.warnings?.map((w) => (
              <p key={w} className="font-mono text-xs text-gap-hi">
                ⚠ {w}
              </p>
            ))}
          </div>

          {/* the brief, laid on a proofing sheet with a red margin rule. The sheet
              fills the column and the paste scrolls *inside* it — a long JD never
              grows the page. */}
          <Sheet className="relative overflow-hidden desk:min-h-0 desk:flex-1">
            <div aria-hidden className="pointer-events-none absolute inset-y-0 left-11 w-px bg-gap/30" />
            <Textarea
              id="jd"
              value={jd}
              onChange={(e) => setJd(e.target.value)}
              placeholder="Paste the full job description…"
              className="h-96 resize-none field-sizing-fixed overflow-y-auto border-0 bg-transparent py-5 pr-5 pl-16 text-base leading-relaxed text-ink shadow-none placeholder:text-ink-soft/60 focus-visible:ring-0 desk:h-full"
            />
          </Sheet>
        </motion.div>

        <motion.div variants={rise} className="flex flex-col gap-5 desk:min-h-0">
          <Eyebrow n="02">your sources · pdf or .tex</Eyebrow>

          {/* pick from the saved library (all pre-checked) — no forced re-upload.
              A long library scrolls here rather than pushing the button off-screen;
              the slack goes to the drop target below, not to a hole in the column. */}
          <div className="space-y-2 desk:max-h-[45%] desk:shrink-0 desk:overflow-y-auto">
            {resumesLoading && <ListSkeleton rows={2} />}
            {!resumesLoading && resumes.length > 0 && (
              <>
                <Sheet as="ul" sm className="divide-y divide-border overflow-hidden">
                  {resumes.map((r) => (
                    <li key={r.id}>
                      <label className="flex cursor-pointer items-center gap-3 px-4 py-2.5">
                        <input
                          type="checkbox"
                          checked={selected.includes(r.id)}
                          onChange={() => toggle(r.id)}
                          className="size-4 accent-marigold"
                        />
                        <span className="truncate font-mono text-sm text-ink">{r.label || r.filename}</span>
                        <span className="ml-auto flex shrink-0 items-center gap-2">
                          {r.format === 'pdf' && (
                            <span className="font-mono text-[10px] tracking-[0.15em] text-cream-soft uppercase">
                              pdf
                            </span>
                          )}
                          {r.is_default && (
                            <span className="rounded bg-marigold/20 px-2 py-0.5 font-mono text-[10px] tracking-[0.15em] text-marigold uppercase">
                              default
                            </span>
                          )}
                        </span>
                      </label>
                    </li>
                  ))}
                </Sheet>
                <p className="font-mono text-[11px] text-cream-soft">
                  all selected — we pick the closest; uncheck any to exclude. a dropped file is used for this run.
                </p>
              </>
            )}

            {!resumesLoading && resumes.length === 0 && (
              <p className="font-mono text-[11px] leading-relaxed text-cream-soft">
                No saved résumés yet — drop one below for this run, or{' '}
                <Link to="/library" className="text-marigold underline-offset-2 hover:underline">
                  add it to your library
                </Link>{' '}
                to reuse it on every run.
              </p>
            )}
          </div>

          <Dropzone files={files} onChange={setFiles} className="desk:min-h-0 desk:flex-1" />

          <div className="shrink-0 space-y-3 pt-2">
            {(create.isError || upload.isError) && (
              <p role="alert" className="font-mono text-sm text-gap-hi">
                {((create.error || upload.error) as Error).message}
              </p>
            )}
            {sourcesReady && !setupReady && (
              <p className="font-mono text-xs text-cream-soft">
                Confirm your profile and set a target role above before tailoring.
              </p>
            )}
            <Button
              onClick={() => void submit()}
              disabled={!canTailor}
              className="h-14 w-full rounded-md bg-marigold font-mono text-sm tracking-[0.2em] text-ink uppercase shadow-[0_10px_30px_-12px_rgba(243,180,31,0.7)] transition hover:bg-marigold hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-35 disabled:shadow-none"
            >
              {create.isPending ? 'sending to the press…' : upload.isPending ? 'reading résumé…' : 'Tailor my résumé →'}
            </Button>
            <p className="text-center font-mono text-xs text-cream-soft">
              a real run takes a few minutes — the LLM tailors and scores.
            </p>
          </div>
        </motion.div>
      </div>
    </motion.div>
  )
}
