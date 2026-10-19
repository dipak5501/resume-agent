import { motion } from 'motion/react'

import { AnswerBank } from '@/components/AnswerBank'
import { SectionHeading } from '@/components/ui/SectionHeading'
import { rise, stagger, useEntrance } from '@/lib/motion'

// Answer bank (T14 — split out of the old combined Profile page). Reusable
// screening answers the extension fills, and drafts from when left blank.
export function Answers() {
  const entrance = useEntrance()
  return (
    <motion.div
      variants={stagger}
      {...entrance}
      className="mx-auto max-w-4xl space-y-8 px-6 py-16 lg:py-20"
    >
      <motion.div variants={rise}>
        <SectionHeading kicker="set up & track · answer bank" title={<>Your answers<span className="text-marigold">.</span></>}>
          Reusable screening answers. <span className="text-cream">Verbatim</span> facts fill as-is;{' '}
          <span className="text-cream">adaptable</span> templates get tailored to each job. The
          extension drafts anything you leave blank — you always review before submitting.
        </SectionHeading>
      </motion.div>
      <motion.div variants={rise}>
        <AnswerBank />
      </motion.div>
    </motion.div>
  )
}
