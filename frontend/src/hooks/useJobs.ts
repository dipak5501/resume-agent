import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  answerQuestion,
  ApiError,
  armAutoApply,
  askResumeChat,
  createJob,
  fetchJdFromUrl,
  getFitNote,
  getJob,
  listApplications,
  listJobs,
  markApplied,
  resolveBoardPosting,
  saveLocal,
  sendFeedback,
  setApplicationStatus,
  setAutoApply,
} from '@/lib/api'
import type { AppStatus } from '@/lib/types'
import type { Job } from '@/lib/types'

export function useCreateJob() {
  return useMutation({
    mutationFn: ({
      jd,
      files,
      resumeIds,
      applyUrl,
      title,
      company,
    }: {
      jd: string
      files?: File[]
      resumeIds?: string[]
      applyUrl?: string | null
      title?: string | null
      company?: string | null
    }) => createJob(jd, { files, resumeIds, applyUrl, title, company }),
  })
}

/** Fetch a JD from a job link (T10). Caller fills the editable JD field on success. */
export function useJdFromUrl() {
  return useMutation({ mutationFn: (url: string) => fetchJdFromUrl(url) })
}

/** A URL handoff fetches once per visit, without an effect/mutation double-run
 * in StrictMode. No focus refetch may overwrite someone's work in Compose. */
export function useJdHandoff(url: string, fromBoard: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: ['jd-handoff', fromBoard, url],
    queryFn: async () => {
      try {
        return await (fromBoard ? resolveBoardPosting(url) : fetchJdFromUrl(url))
      } catch (error) {
        if (fromBoard && error instanceof ApiError && [404, 410].includes(error.status)) {
          void qc.invalidateQueries({ queryKey: ['board'] })
        }
        throw error
      }
    },
    enabled: !!url,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    refetchOnMount: 'always',
    gcTime: 0,
  })
}

/** All past runs for the History section (T14). */
export function useJobsList() {
  return useQuery({ queryKey: ['jobs'], queryFn: listJobs })
}

/** Filed applications, or the saved-but-not-applied list. */
export function useApplications(bucket: 'filed' | 'saved' = 'filed') {
  return useQuery({ queryKey: ['applications', bucket], queryFn: () => listApplications(bucket) })
}

export function useSetApplicationStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: AppStatus }) => setApplicationStatus(id, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['applications'] }),
  })
}

export function useFitNote(id: string) {
  return useQuery({ queryKey: ['fit', id], queryFn: () => getFitNote(id), retry: false })
}

export function useResumeChat(id: string) {
  return useMutation({ mutationFn: (message: string) => askResumeChat(id, message) })
}

export function useSetAutoApply() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (enabled: boolean) => setAutoApply(enabled),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['profile'] }),
  })
}

export function useArmAutoApply() {
  return useMutation({ mutationFn: (id: string) => armAutoApply(id) })
}

export function useMarkApplied() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => markApplied(id),
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: ['job', id] })
      qc.invalidateQueries({ queryKey: ['jobs'] })
      qc.invalidateQueries({ queryKey: ['applications'] })
    },
  })
}

/** Save the tailored PDF into the repo folder + tracker CSV (local-dev only). */
export function useSaveLocal() {
  return useMutation({ mutationFn: (id: string) => saveLocal(id) })
}

/** Poll a job every 2s until it finishes (long jobs — minutes). */
export function useJob(id: string | null) {
  return useQuery({
    queryKey: ['job', id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    // A missing/expired id (404) is terminal — don't retry it, so the query
    // settles to error fast and /tailor/:jobId shows its not-found state instead
    // of polling forever (T14). Transient errors still get a few retries.
    retry: (n, err) => !(err instanceof ApiError && err.status === 404) && n < 3,
    refetchInterval: (q) => {
      if (q.state.status === 'error') return false // stop on a gone/failed job
      const s = (q.state.data as Job | undefined)?.status
      return s === 'done' || s === 'error' ? false : 2000
    },
  })
}

/** Draft an application answer for this run (T24). The server owns the per-job
 *  log, so we refetch the job rather than keep a second copy client-side —
 *  which is also what makes the log survive a reload. */
export function useAnswerQuestion(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (question: string) => answerQuestion(id, question),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job', id] }),
  })
}

export function useFeedback(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (feedback: string) => sendFeedback(id, feedback),
    // a new round is queued server-side; resume polling immediately
    onSuccess: () => qc.invalidateQueries({ queryKey: ['job', id] }),
  })
}
