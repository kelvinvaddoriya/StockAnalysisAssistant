import { authedFetch } from './supabase'

// processMessage replaces apiUrl for C1Chat / useThreadManager so we can attach
// the Supabase access token. The backend's /api/chat expects only the LAST
// user message; full history lives in the langgraph checkpointer keyed on
// threadId.
type ChatMessage = { id: string; role: string; content?: string }

// Exported for tests — the rate-limit branch in particular is not reachable
// through the UI.
export async function chatProcessMessage({
  threadId, messages, responseId, abortController,
}: {
  threadId: string
  messages: ChatMessage[]
  responseId: string
  abortController: AbortController
}): Promise<Response> {
  const lastUser = [...messages].reverse().find(m => m.role === 'user')
  if (!lastUser) throw new Error('No user message to send')
  const res = await authedFetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      prompt: { content: String(lastUser.content), id: lastUser.id, role: 'user' },
      threadId,
      responseId,
    }),
    signal: abortController.signal,
  })
  if (res.status === 429) {
    // Rate limited. Show the backend's reason as the assistant's reply rather
    // than letting C1Chat fail on a non-2xx response with no explanation.
    const detail = await res.json().then(b => b?.detail).catch(() => null)
    const text = `_${detail ?? 'Too many enquiries. Please wait a few minutes and try again.'}_`
    return new Response(text, { status: 200, headers: { 'Content-Type': 'text/plain' } })
  }
  return res
}
