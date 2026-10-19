import { useProfile, useResumes } from '@/hooks/useProfile'

const TAILORED_KEY = 'has-tailored'

/** Remember that a run was started. The job list itself is in-memory on the
 *  backend, so it empties on every restart — without this, a set-up user would
 *  fall back to the first-run intro each time the server bounced. */
export const markTailored = () => localStorage.setItem(TAILORED_KEY, '1')

/** Setup gate, in checklist order: a résumé on file, the parsed profile
 *  confirmed, and a target role. `null` while those are loading. Tailoring
 *  stays closed until every step is true. */
export function useSetupProgress(): boolean[] | null {
  const profile = useProfile()
  const resumes = useResumes()
  if (profile.isPending || resumes.isPending) return null
  const data = profile.data
  return [
    (resumes.data?.length ?? 0) > 0,
    Boolean(data?.profile_confirmed && (data.name || data.email)),
    Boolean(data?.target_role?.trim()),
  ]
}

export function useCanTailor(): boolean | null {
  const progress = useSetupProgress()
  if (!progress) return null
  return progress.every(Boolean)
}
