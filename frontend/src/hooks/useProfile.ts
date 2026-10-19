import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import {
  deleteResume,
  getProfile,
  listResumes,
  setDefaultResume,
  updateProfile,
  uploadResume,
} from '@/lib/api'
import type { ProfileIn } from '@/lib/types'

export function useProfile() {
  return useQuery({ queryKey: ['profile'], queryFn: getProfile })
}

export function useUpdateProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (p: ProfileIn) => updateProfile(p),
    onSuccess: (data) => qc.setQueryData(['profile'], data),
  })
}

export function useResumes() {
  return useQuery({ queryKey: ['resumes'], queryFn: listResumes })
}

/** Any résumé write refetches the library. */
function useResumeWrite<A>(fn: (arg: A) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: fn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['resumes'] }),
  })
}

export function useUploadResume() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, label }: { file: File; label?: string }) => uploadResume(file, label),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['resumes'] })
      qc.invalidateQueries({ queryKey: ['profile'] })
    },
  })
}
export const useDeleteResume = () => useResumeWrite((id: string) => deleteResume(id))
export const useSetDefaultResume = () => useResumeWrite((id: string) => setDefaultResume(id))
