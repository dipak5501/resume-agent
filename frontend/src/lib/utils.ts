import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** The Board's 14-day publication window (backend board_policy). */
export const MAX_AGE_MS = 14 * 24 * 60 * 60 * 1000

/** Posting timestamps arrive as naive UTC from SQLite; also accept an explicit offset. */
export function postingTime(iso: string): number {
  return Date.parse(/(?:Z|[+-]\d{2}:\d{2})$/i.test(iso) ? iso : `${iso}Z`)
}
