import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { createAnswer, deleteAnswer, listAnswers, updateAnswer } from '@/lib/api'
import type { AnswerIn } from '@/lib/types'

export function useAnswers() {
  return useQuery({ queryKey: ['answers'], queryFn: listAnswers })
}

/** Any answer write refetches the bank. */
function useAnswerWrite<A>(fn: (arg: A) => Promise<unknown>) {
  const qc = useQueryClient()
  return useMutation({ mutationFn: fn, onSuccess: () => qc.invalidateQueries({ queryKey: ['answers'] }) })
}

export const useCreateAnswer = () => useAnswerWrite((body: AnswerIn) => createAnswer(body))
export const useUpdateAnswer = () =>
  useAnswerWrite(({ id, body }: { id: string; body: AnswerIn }) => updateAnswer(id, body))
export const useDeleteAnswer = () => useAnswerWrite((id: string) => deleteAnswer(id))
