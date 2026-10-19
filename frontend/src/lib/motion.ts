import { useReducedMotion } from 'motion/react'
import type { Variants } from 'motion/react'

// One motion vocabulary for the proofing desk. The signature easing and the
// durations live here so every entrance/transition is consistent and tunable in
// one place. The atomic CSS effects — the highlighter swipe and the stamp press
// — deliberately stay in index.css and are NOT ported to JS.
//
// prefers-reduced-motion is honored globally by <MotionConfig reducedMotion="user">
// in main.tsx: it drops the transforms below and keeps opacity, so every entrance
// collapses to a plain fade (or instant) when the OS setting is on.

/** ease-out expo — the curve the whole desk moves on. */
export const EASE = [0.16, 1, 0.3, 1] as const

export const DUR = {
  fast: 0.3,
  base: 0.6,
} as const

/** A sheet settling onto the desk: rises a little and fades in. */
export const rise: Variants = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: DUR.base, ease: EASE } },
}

/** A container that deals its children in, one after another. */
export const stagger: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.09, delayChildren: 0.05 } },
}

/** Route/page change: a quick crossfade — opacity only, so it never fights the
 *  inner content's own entrance stagger. */
export const pageFade: Variants = {
  hidden: { opacity: 0 },
  show: { opacity: 1, transition: { duration: DUR.fast, ease: EASE } },
  exit: { opacity: 0, transition: { duration: 0.2, ease: 'linear' } },
}

/**
 * Entrance props for a motion container (pair with `variants={rise|stagger}`).
 * Normally plays the hidden→show reveal; under prefers-reduced-motion it renders
 * straight to the visible state (`initial={false}`) so there is no opacity reveal
 * — motion otherwise leaves reduced-motion elements stuck at their hidden opacity,
 * which blanks the page. This is the accessibility fallback, applied everywhere.
 */
export function useEntrance(): { initial: false | 'hidden'; animate: 'show' } {
  const reduced = useReducedMotion()
  return { initial: reduced ? false : 'hidden', animate: 'show' }
}
