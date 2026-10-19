import { useState } from 'react'
import { motion } from 'motion/react'

import { Button } from '@/components/ui/button'
import { Sheet } from '@/components/ui/Sheet'
import { useResumeChat } from '@/hooks/useJobs'
import { rise } from '@/lib/motion'

interface Turn {
  role: 'user' | 'assistant'
  content: string
}

export function ResumeChat({ jobId }: { jobId: string }) {
  const ask = useResumeChat(jobId)
  const [message, setMessage] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])

  async function send() {
    const text = message.trim()
    if (!text || ask.isPending) return
    setMessage('')
    setTurns((prev) => [...prev, { role: 'user', content: text }])
    try {
      const res = await ask.mutateAsync(text)
      setTurns((prev) => [...prev, { role: 'assistant', content: res.answer }])
    } catch (err) {
      setTurns((prev) => [...prev, { role: 'assistant', content: (err as Error).message }])
    }
  }

  return (
    <Sheet as={motion.section} variants={rise} className="p-7">
      <h2 className="font-serif text-2xl text-ink">Does this résumé support this job?</h2>
      <p className="mt-2 text-sm leading-relaxed text-ink-soft">
        Answers stay inside the profile and the résumé already stored. Nothing here is invented onto the page.
      </p>
      <ul className="mt-4 space-y-3">
        {turns.map((turn, i) => (
          <li key={`${turn.role}-${i}`} className={`text-sm leading-relaxed ${turn.role === 'user' ? 'text-ink' : 'text-ink-soft'}`}>
            <span className="mr-2 font-mono text-[10px] tracking-[0.14em] uppercase">{turn.role === 'user' ? 'You' : 'Note'}</span>
            {turn.content}
          </li>
        ))}
      </ul>
      <form
        className="mt-4 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          void send()
        }}
      >
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder="Ask about this résumé and this job"
          className="min-w-0 flex-1 rounded-md border border-ink/15 bg-transparent px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-soft/60 focus:border-marigold focus:outline-none"
        />
        <Button type="submit" disabled={ask.isPending || !message.trim()} className="rounded-md bg-marigold px-3 font-mono text-[11px] tracking-[0.14em] text-ink uppercase">
          {ask.isPending ? '…' : 'Ask'}
        </Button>
      </form>
    </Sheet>
  )
}
