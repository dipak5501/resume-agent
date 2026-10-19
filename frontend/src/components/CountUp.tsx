import { useEffect, useState } from 'react'
import { animate, useReducedMotion } from 'motion/react'

import { EASE } from '@/lib/motion'

export function CountUp({
  to,
  from = 0,
  duration = 1.1,
  delay = 0,
  className,
}: {
  to: number
  from?: number
  duration?: number
  delay?: number
  className?: string
}) {
  const reduce = useReducedMotion()
  const [n, setN] = useState(from)
  useEffect(() => {
    if (reduce) return // render shows `to` directly; no animation
    const controls = animate(from, to, {
      duration,
      delay,
      ease: EASE,
      onUpdate: (v) => setN(Math.round(v)),
    })
    return () => controls.stop()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [to, reduce])
  return <span className={className}>{reduce ? to : n}</span>
}
