import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Send } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { api } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from '@/components/ui/sheet'

interface ChatMessage {
  role: 'user' | 'assistant'
  text: string
}

interface ChatOverlayProps {
  studentId: string
  weakSubjects: string[]
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function ChatOverlay({ studentId, weakSubjects, open, onOpenChange }: ChatOverlayProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const queryClient = useQueryClient()

  const contextQuery = useQuery({
    queryKey: ['chat-context', studentId],
    queryFn: () => api.getChatContext(studentId),
    enabled: open,
  })

  const sendMutation = useMutation({
    mutationFn: (message: string) => api.postChat(studentId, message),
    onSuccess: (data) => {
      setMessages((prev) => [...prev, { role: 'assistant', text: data.reply }])
      // The concierge may have just created/updated a plan (schedule_and_save_plan_tool) —
      // refetch rather than guess from the reply text so the dashboard tile stays in sync.
      queryClient.invalidateQueries({ queryKey: ['plan', studentId] })
    },
    onError: () => {
      setMessages((prev) => [...prev, { role: 'assistant', text: "Sorry, I couldn't reach the Student Guide." }])
    },
  })

  function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed) return
    setMessages((prev) => [...prev, { role: 'user', text: trimmed }])
    setInput('')
    sendMutation.mutate(trimmed)
  }

  const hasPlan = !!contextQuery.data?.semester_plan
  const showQuickQuestions = messages.length === 0 && contextQuery.isSuccess && !contextQuery.isError

  const quickQuestions = hasPlan
    ? [
        'How many credits do I still need?',
        'What electives are left for me?',
        'Recalculate my plan for next semester',
      ]
    : [
        'Plan my next semester',
        'Plan my whole remaining degree',
        ...weakSubjects.map((subject) => `Focus on ${subject}`),
      ]

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="flex flex-col p-0">
        <SheetHeader>
          <SheetTitle>Student Guide</SheetTitle>
          <SheetDescription>
            {contextQuery.isLoading
              ? 'Loading your context…'
              : contextQuery.isError
                ? "Couldn't load your context, but you can still chat."
                : hasPlan
                  ? 'Ask me anything about your existing plan.'
                  : "Let's build your semester plan."}
          </SheetDescription>
        </SheetHeader>

        <div className="flex-1 overflow-y-auto p-4">
          {messages.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {contextQuery.isError
                ? 'Type your question below to get started.'
                : hasPlan
                  ? 'Pick a question below, or type your own.'
                  : 'Pick what you want to do below, or tell me in your own words.'}
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {messages.map((m, i) => (
                <div
                  key={i}
                  className={`max-w-[85%] rounded-lg px-3 py-2 text-sm ${
                    m.role === 'user'
                      ? 'ml-auto bg-primary text-primary-foreground'
                      : 'bg-secondary text-secondary-foreground [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-4 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:space-y-1 [&_ol]:pl-4 [&_strong]:font-semibold [&_a]:break-all [&_a]:underline [&_a]:underline-offset-2'
                  }`}
                >
                  {m.role === 'assistant' ? (
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.text}</ReactMarkdown>
                  ) : (
                    m.text
                  )}
                </div>
              ))}
              {sendMutation.isPending && (
                <div className="max-w-[85%] rounded-lg bg-secondary px-3 py-2 text-sm text-muted-foreground">
                  Thinking…
                </div>
              )}
            </div>
          )}
        </div>

        {showQuickQuestions && (
          <div className="flex flex-wrap gap-2 border-t border-border p-4">
            {quickQuestions.map((q) => (
              <Button key={q} variant="outline" size="sm" onClick={() => send(q)}>
                {q}
              </Button>
            ))}
          </div>
        )}

        <form
          onSubmit={(e) => {
            e.preventDefault()
            send(input)
          }}
          className="flex gap-2 border-t border-border p-4"
        >
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Ask a follow-up, or add a comment…"
            className="flex-1 rounded-md border border-input bg-transparent px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
          />
          <Button type="submit" size="icon" disabled={!input.trim() || sendMutation.isPending}>
            <Send />
          </Button>
        </form>
      </SheetContent>
    </Sheet>
  )
}
