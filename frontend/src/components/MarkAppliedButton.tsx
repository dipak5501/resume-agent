import { useMarkApplied } from '@/hooks/useJobs'

// Files a finished run under Set up & track and keeps that run's résumé.
export function MarkAppliedButton({
  jobId,
  applied,
  tone = 'paper',
  block = false,
  label = 'I applied; log it',
}: {
  jobId: string
  applied: boolean
  tone?: 'paper' | 'desk'
  block?: boolean
  label?: string
}) {
  const mark = useMarkApplied()
  const filed = applied || mark.isSuccess
  const desk = tone === 'desk'
  return (
    <span className={block ? 'block' : 'contents'}>
      <button
        type="button"
        onClick={() => mark.mutate(jobId)}
        disabled={filed || mark.isPending}
        className={
          desk
            ? 'mt-3 w-full rounded-md border border-dashed border-cream-soft/25 px-5 py-2.5 font-mono text-xs tracking-[0.15em] text-cream-soft uppercase transition hover:border-marigold/40 hover:text-cream disabled:opacity-60'
            : 'shrink-0 rounded border border-ink/15 px-2 py-1 font-mono text-[10px] tracking-[0.14em] text-ink uppercase transition hover:border-marigold hover:text-marigold disabled:opacity-60'
        }
      >
        {filed ? 'Applied' : mark.isPending ? 'filing…' : label}
      </button>
      {mark.isError && (
        <span role="alert" className={`font-mono text-[10px] ${desk ? 'mt-1 block text-gap-hi' : 'text-gap-hi'}`}>
          {(mark.error as Error).message}
        </span>
      )}
    </span>
  )
}
