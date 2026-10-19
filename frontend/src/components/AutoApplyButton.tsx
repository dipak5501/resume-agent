import { useState } from 'react'

import { useArmAutoApply } from '@/hooks/useJobs'
import { useExtensionStatus } from '@/hooks/useExtension'
import { useProfile } from '@/hooks/useProfile'

export function AutoApplyButton({
  jobId,
  applyUrl,
  applied,
}: {
  jobId: string
  applyUrl: string | null
  applied: boolean
}) {
  const extension = useExtensionStatus()
  const profile = useProfile()
  const arm = useArmAutoApply()
  const [note, setNote] = useState<string | null>(null)
  if (!applyUrl || applied) return null
  const enabled = Boolean(profile.data?.auto_apply)

  async function go() {
    setNote(null)
    if (!extension.active) {
      setNote('The extension is not active. Load unpacked extension/dist in Chrome, then reload this page. Nothing was submitted.')
      return
    }
    if (!enabled) {
      setNote('Turn on Auto-apply under Set up & track. Nothing was submitted.')
      return
    }
    try {
      const armed = await arm.mutateAsync(jobId)
      window.open(armed.apply_url, '_blank', 'noopener')
      setNote('Opened this one application. The extension fills it and submits only if every required field is known.')
    } catch (err) {
      setNote((err as Error).message || 'Nothing was submitted.')
    }
  }

  return (
    <div className="mt-3">
      <button
        type="button"
        onClick={() => void go()}
        disabled={arm.isPending}
        className="w-full rounded-md border border-marigold/50 bg-marigold/10 px-5 py-3 text-left font-mono text-xs tracking-[0.14em] text-cream uppercase transition hover:bg-marigold/15 disabled:opacity-50"
      >
        {arm.isPending ? 'Opening…' : 'Auto-apply this job'}
      </button>
      {!enabled && (
        <p className="mt-2 font-mono text-[11px] leading-relaxed text-cream-soft">
          The switch is off. Turn it on under Set up &amp; track first.
        </p>
      )}
      {note && <p className="mt-2 font-mono text-[11px] leading-relaxed text-cream-soft">{note}</p>}
    </div>
  )
}
