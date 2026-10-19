import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { Sheet } from '@/components/ui/Sheet'
import { useSetupProgress } from '@/hooks/useSetup'
import { useProfile, useUpdateProfile, useUploadResume } from '@/hooks/useProfile'
import { toProfileIn } from '@/lib/profileForm'
import { filledSummary, isResumeFile } from '@/lib/resume'

const COLLAPSE_KEY = 'onboarding-collapsed'

// The checklist copy. A step's blurb + cta only ever render while it is undone,
// so nothing here needs to know the live state. The résumé step's upload control
// is rendered separately so the "filled" note can stay after the step checks off.
const STEPS = [
  {
    title: 'Add a résumé',
    blurb: 'Drop a PDF or .tex. We fill your name and contact from it.',
  },
  {
    title: 'Confirm your profile',
    blurb: 'Check the name and contact we read. Tailoring stays closed until you confirm.',
  },
  {
    title: 'Set a target role',
    blurb: 'Name the role you want. Location and work authorization are optional.',
  },
] as const

const fieldCls =
  'mt-1 w-full rounded border border-ink/15 bg-transparent px-2 py-1.5 font-mono text-xs text-ink placeholder:text-ink-soft/50 focus:border-marigold focus:outline-none'

function ConfirmProfile() {
  const { data: profile } = useProfile()
  const save = useUpdateProfile()
  const named = Boolean(profile?.name || profile?.email)
  if (!profile) return null
  const bits = [profile.name, profile.email, profile.phone, profile.location].filter(Boolean)
  return (
    <div className="space-y-1">
      <p className="font-mono text-[11px] text-ink-soft">
        {bits.length ? bits.join(' · ') : 'Nothing read yet.'}{' '}
        <Link to="/profile" className="text-ink underline-offset-2 hover:underline">Edit</Link>
      </p>
      {named ? (
        <button
          type="button"
          className="ob-cta disabled:opacity-40"
          disabled={save.isPending}
          onClick={() => save.mutate(toProfileIn(profile, { profile_confirmed: true }))}
        >
          {save.isPending ? 'saving…' : 'Confirm profile →'}
        </button>
      ) : (
        <Link to="/profile" className="ob-cta">Add your name on Profile →</Link>
      )}
    </div>
  )
}

function TargetRole() {
  const { data: profile } = useProfile()
  const save = useUpdateProfile()
  const [role, setRole] = useState(profile?.target_role ?? '')
  const [location, setLocation] = useState(profile?.location ?? '')
  const [workAuth, setWorkAuth] = useState(profile?.work_auth ?? '')
  if (!profile) return null
  return (
    <form
      className="space-y-1.5"
      onSubmit={(e) => {
        e.preventDefault()
        if (!role.trim()) return
        save.mutate(toProfileIn(profile, {
          target_role: role.trim(),
          location: location.trim(),
          work_auth: workAuth.trim(),
        }))
      }}
    >
      <input className={fieldCls} value={role} onChange={(e) => setRole(e.target.value)} placeholder="Target role" required />
      <input className={fieldCls} value={location} onChange={(e) => setLocation(e.target.value)} placeholder="Location (optional)" />
      <input className={fieldCls} value={workAuth} onChange={(e) => setWorkAuth(e.target.value)} placeholder="Work authorization (optional)" />
      <button type="submit" className="ob-cta disabled:opacity-40" disabled={save.isPending || !role.trim()}>
        {save.isPending ? 'saving…' : 'Save target role →'}
      </button>
    </form>
  )
}

function ResumeUpload({ onFilled }: { onFilled: (note: string) => void }) {
  const upload = useUploadResume()
  const inputRef = useRef<HTMLInputElement>(null)

  async function onPick(list: FileList | null) {
    const file = list?.[0]
    if (!file) return
    if (!isResumeFile(file.name)) {
      onFilled('Use a PDF or .tex file.')
      return
    }
    try {
      const saved = await upload.mutateAsync({ file })
      onFilled(filledSummary(saved.filled))
    } catch {
      // upload.isError renders the message
    }
  }

  return (
    <div className="space-y-1">
      <button
        type="button"
        className="ob-cta disabled:opacity-40"
        disabled={upload.isPending}
        onClick={() => inputRef.current?.click()}
      >
        {upload.isPending ? 'reading…' : 'Upload PDF or .tex →'}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.tex,application/pdf"
        className="hidden"
        onChange={(e) => {
          void onPick(e.target.files)
          e.target.value = ''
        }}
      />
      {upload.isError && (
        <p role="alert" className="font-mono text-[11px] text-gap-hi">
          {(upload.error as Error).message}
        </p>
      )}
    </div>
  )
}

// First-run setup (T14): reads real state, guides résumé → profile → extension →
// first tailor. Dismissible (collapses to a slim bar) and resumable; disappears
// for good once every step is done. Native — no tour library.
export function Onboarding() {
  const progress = useSetupProgress()
  const [collapsed, setCollapsed] = useState(() => localStorage.getItem(COLLAPSE_KEY) === '1')
  const [filledNote, setFilledNote] = useState<string | null>(null)

  if (!progress) return null // still loading — don't flash an empty checklist
  const doneCount = progress.filter(Boolean).length
  if (doneCount === STEPS.length) return null // setup complete → gone for good

  const collapse = () => {
    localStorage.setItem(COLLAPSE_KEY, '1')
    setCollapsed(true)
  }
  const expand = () => {
    localStorage.removeItem(COLLAPSE_KEY)
    setCollapsed(false)
  }

  if (collapsed) {
    return (
      <div className="mx-auto max-w-[96rem] px-6 pt-8">
        <button
          onClick={expand}
          className="flex w-full items-center gap-3 rounded-md border border-dashed border-cream-soft/25 px-4 py-2.5 text-left font-mono text-[11px] tracking-[0.16em] text-cream-soft uppercase transition hover:border-marigold/40 hover:text-cream"
        >
          <span className="text-marigold">◔</span>
          Getting set up · {doneCount} of {STEPS.length}
          <span aria-hidden className="ml-auto">resume ↓</span>
        </button>
      </div>
    )
  }

  return (
    <section
      aria-label="Setup checklist"
      className="mx-auto mt-8 max-w-[96rem] px-6"
    >
      <Sheet className="relative overflow-hidden p-6 lg:p-8">
        <div aria-hidden className="pointer-events-none absolute inset-y-0 left-0 w-[3px] bg-marigold" />
        <div className="mb-5 flex items-baseline justify-between gap-4">
          <div>
            <p className="font-mono text-[11px] tracking-[0.28em] text-accent uppercase">
              first — add your résumé
            </p>
            <h2 className="mt-1 font-serif text-2xl text-ink">
              {doneCount} of {STEPS.length} ready
            </h2>
          </div>
          <button
            onClick={collapse}
            className="shrink-0 font-mono text-[11px] tracking-[0.16em] text-ink-soft uppercase underline-offset-4 hover:text-ink hover:underline"
          >
            dismiss
          </button>
        </div>

        <ol className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-3">
          {STEPS.map((s, i) => (
            <li key={s.title} className="flex gap-3">
              <span
                aria-hidden
                className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] ${
                  progress[i]
                    ? 'border-transparent bg-marigold text-ink'
                    : 'border-ink-soft/40 text-ink-soft'
                }`}
              >
                {progress[i] ? '✓' : i + 1}
              </span>
              <div className="space-y-0.5">
                <p className={`font-mono text-sm ${progress[i] ? 'text-ink-soft line-through' : 'text-ink'}`}>
                  {s.title}
                </p>
                {!progress[i] && (
                  <>
                    <p className="text-[13px] leading-snug text-ink-soft">{s.blurb}</p>
                    {i === 0 && <ResumeUpload onFilled={setFilledNote} />}
                    {i === 1 && <ConfirmProfile />}
                    {i === 2 && <TargetRole />}
                  </>
                )}
              </div>
            </li>
          ))}
        </ol>
        {filledNote && (
          <p className="mt-4 font-mono text-xs text-ink-soft">{filledNote}</p>
        )}
      </Sheet>
    </section>
  )
}
