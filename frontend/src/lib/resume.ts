const LABELS: Record<string, string> = {
  name: 'name',
  email: 'email',
  phone: 'phone',
  location: 'location',
  work_auth: 'work authorization',
  github: 'GitHub',
  linkedin: 'LinkedIn',
  portfolio: 'portfolio',
}

/** Sentence shown after a résumé upload writes (or doesn't write) profile fields. */
export function filledSummary(filled: string[]): string {
  if (!filled.length) return 'Saved to your library.'
  const names = filled.map((k) => LABELS[k] ?? k)
  if (names.length === 1) return `Filled ${names[0]} from your résumé.`
  const last = names[names.length - 1]
  return `Filled ${names.slice(0, -1).join(', ')} and ${last} from your résumé.`
}

export const isResumeFile = (name: string) => /\.(tex|pdf)$/i.test(name)
export const isPdfFile = (name: string) => name.toLowerCase().endsWith('.pdf')
