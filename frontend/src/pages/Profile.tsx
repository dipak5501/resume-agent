import { useEffect, useState } from 'react'
import { motion } from 'motion/react'
import { Link } from 'react-router-dom'

import { InlineError } from '@/components/states/InlineError'
import { Button } from '@/components/ui/button'
import { SectionHeading } from '@/components/ui/SectionHeading'
import { Skeleton } from '@/components/ui/Skeleton'
import { useProfile, useUpdateProfile } from '@/hooks/useProfile'
import { rise, stagger, useEntrance } from '@/lib/motion'
import type { ProfileIn } from '@/lib/types'

const EMPTY: ProfileIn = {
  name: '',
  email: '',
  phone: '',
  location: '',
  work_auth: '',
  work_eligible: '',
  needs_sponsorship: '',
  gender: '',
  race: '',
  disability: '',
  veteran: '',
  target_role: '',
  profile_confirmed: false,
  auto_apply: false,
  links: { github: '', linkedin: '', portfolio: '' },
}

const inputCls =
  'w-full rounded-md border border-cream-soft/20 bg-transparent px-3 py-2.5 font-mono text-sm text-cream placeholder:text-cream-soft/40 focus:border-marigold focus:outline-none'

function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block space-y-1.5">
      <span className="font-mono text-[10px] tracking-[0.22em] text-cream-soft uppercase">{label}</span>
      <input className={inputCls} {...props} />
    </label>
  )
}

function Picker({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: [string, string][] // [value, display]
}) {
  return (
    <label className="block space-y-1.5">
      <span className="font-mono text-[10px] tracking-[0.22em] text-cream-soft uppercase">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`${inputCls} appearance-none`}
      >
        <option value="">— not set —</option>
        {options.map(([v, d]) => (
          <option key={v} value={v}>
            {d}
          </option>
        ))}
      </select>
    </label>
  )
}

const YES_NO: [string, string][] = [
  ['yes', 'Yes'],
  ['no', 'No'],
]
const YES_NO_DECLINE: [string, string][] = [...YES_NO, ['decline', 'Decline to self-identify']]

// Identity + links (T14 — the résumé library and answer bank are now their own
// sections). Set up once; every tailored run and the extension read from here.
// Field-grid loading placeholder, shaped like the form below it (label + input).
function FormSkeleton() {
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-2.5 w-24" />
            <Skeleton className="h-11 w-full" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="space-y-1.5">
            <Skeleton className="h-2.5 w-20" />
            <Skeleton className="h-11 w-full" />
          </div>
        ))}
      </div>
    </div>
  )
}

export function Profile() {
  const { data: profile, isPending, isError, refetch } = useProfile()
  const save = useUpdateProfile()
  const [form, setForm] = useState<ProfileIn>(EMPTY)
  const entrance = useEntrance()

  // hydrate the form once the profile loads (null fields → empty strings)
  useEffect(() => {
    if (!profile) return
    // one-shot hydrate from the server fetch — the legitimate setState-in-effect case
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm({
        name: profile.name ?? '',
        email: profile.email ?? '',
        phone: profile.phone ?? '',
        location: profile.location ?? '',
        work_auth: profile.work_auth ?? '',
        work_eligible: profile.work_eligible ?? '',
        needs_sponsorship: profile.needs_sponsorship ?? '',
        gender: profile.gender ?? '',
        race: profile.race ?? '',
        disability: profile.disability ?? '',
        veteran: profile.veteran ?? '',
        target_role: profile.target_role ?? '',
        profile_confirmed: profile.profile_confirmed,
        auto_apply: profile.auto_apply,
        links: {
          github: profile.links?.github ?? '',
          linkedin: profile.links?.linkedin ?? '',
          portfolio: profile.links?.portfolio ?? '',
        },
      })
  }, [profile])

  const set = (k: keyof ProfileIn) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }))
  const setVal = (k: keyof ProfileIn) => (v: string) => setForm((f) => ({ ...f, [k]: v }))
  const setLink = (k: keyof ProfileIn['links']) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, links: { ...f.links, [k]: e.target.value } }))

  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto max-w-4xl space-y-10 px-6 py-16 lg:py-20"
    >
      <motion.div variants={rise}>
        <SectionHeading kicker="set up & track · profile" title={<>Your details<span className="text-marigold">.</span></>}>
          Identity &amp; links live here — reused on every tailored run and by the autofill extension.
          A PDF or .tex in the{' '}
          <Link to="/library" className="text-marigold underline-offset-2 hover:underline">
            library
          </Link>{' '}
          fills any blank fields.
        </SectionHeading>
      </motion.div>

      <motion.div variants={rise}>
      {isPending ? (
        <FormSkeleton />
      ) : isError ? (
        <InlineError onRetry={() => refetch()}>
          Couldn&rsquo;t load your profile — is the backend running?
        </InlineError>
      ) : (
      <section className="space-y-5">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="target role" value={form.target_role ?? ''} onChange={set('target_role')} placeholder="Backend engineer" />
          <Field label="name" value={form.name ?? ''} onChange={set('name')} placeholder="Ada Lovelace" />
          <Field label="email" value={form.email ?? ''} onChange={set('email')} placeholder="ada@example.com" />
          <Field label="phone" value={form.phone ?? ''} onChange={set('phone')} placeholder="+1 …" />
          <Field label="location" value={form.location ?? ''} onChange={set('location')} placeholder="Long Beach, CA" />
          <Field label="work authorization" value={form.work_auth ?? ''} onChange={set('work_auth')} placeholder="US citizen / H-1B / …" />
        </div>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Field label="github" value={form.links.github ?? ''} onChange={setLink('github')} placeholder="github.com/…" />
          <Field label="linkedin" value={form.links.linkedin ?? ''} onChange={setLink('linkedin')} placeholder="linkedin.com/in/…" />
          <Field label="portfolio" value={form.links.portfolio ?? ''} onChange={setLink('portfolio')} placeholder="yoursite.com" />
        </div>

        {/* T17 — work eligibility: lets the extension answer those Yes/No radios */}
        <div className="border-t border-desk-line pt-6">
          <p className="mb-3 font-mono text-[11px] tracking-[0.22em] text-marigold uppercase">
            work eligibility
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Picker label="legally eligible to work?" value={form.work_eligible ?? ''} onChange={setVal('work_eligible')} options={YES_NO} />
            <Picker label="need visa sponsorship?" value={form.needs_sponsorship ?? ''} onChange={setVal('needs_sponsorship')} options={YES_NO} />
          </div>
        </div>

        {/* T17 — voluntary EEO self-ID. Fills demographic questions from YOUR values;
            disability/veteran default to "No" (your choice) but are always flagged for review. */}
        <div className="border-t border-desk-line pt-6">
          <p className="font-mono text-[11px] tracking-[0.22em] text-marigold uppercase">
            voluntary self-identification
          </p>
          <p className="mt-1.5 mb-3 max-w-xl text-[13px] leading-relaxed text-cream-soft">
            All optional and voluntary. The extension fills these from your values and{' '}
            <span className="text-cream">always flags them for your review</span> before you submit —
            it never submits for you.
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="gender" value={form.gender ?? ''} onChange={set('gender')} placeholder="e.g. Male / Female / Non-binary" />
            <Field label="race / ethnicity" value={form.race ?? ''} onChange={set('race')} placeholder="e.g. Asian / Two or more races" />
            <Picker label="disability status" value={form.disability ?? ''} onChange={setVal('disability')} options={YES_NO_DECLINE} />
            <Picker label="veteran status" value={form.veteran ?? ''} onChange={setVal('veteran')} options={YES_NO_DECLINE} />
          </div>
        </div>

        <div className="flex items-center gap-4">
          <Button
            onClick={() => save.mutate({ ...form, profile_confirmed: Boolean(form.name || form.email) })}
            disabled={save.isPending}
            className="h-11 rounded-md bg-marigold px-6 font-mono text-xs tracking-[0.2em] text-ink uppercase transition hover:bg-marigold hover:brightness-95 disabled:opacity-40"
          >
            {save.isPending ? 'saving…' : 'Save profile'}
          </Button>
          {save.isSuccess && !save.isPending && (
            <span className="font-mono text-xs text-cream-soft">saved ✓</span>
          )}
        </div>
      </section>
      )}
      </motion.div>
    </motion.div>
  )
}
