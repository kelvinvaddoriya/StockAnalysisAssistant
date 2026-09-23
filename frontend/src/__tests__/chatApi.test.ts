import { describe, it, expect, vi, beforeEach } from 'vitest'
import { chatProcessMessage } from '../chatApi'

const authedFetch = vi.fn()

vi.mock('../supabase', () => ({
  supabase: { auth: { getSession: vi.fn() } },
  authedFetch: (...args: unknown[]) => authedFetch(...args),
}))

function call(messages: { id: string; role: string; content?: string }[]) {
  return chatProcessMessage({
    threadId: 'thread-1',
    messages,
    responseId: 'resp-1',
    abortController: new AbortController(),
  })
}

const USER_MSG = { id: 'm1', role: 'user', content: 'What is AAPL trading at?' }

beforeEach(() => {
  authedFetch.mockReset()
  authedFetch.mockResolvedValue(new Response('ok', { status: 200 }))
})

describe('chatProcessMessage — request shape', () => {
  it('posts the last user message to /api/chat', async () => {
    await call([USER_MSG])
    const [url, init] = authedFetch.mock.calls[0]
    expect(url).toBe('/api/chat')
    expect(init.method).toBe('POST')
    expect(JSON.parse(init.body)).toEqual({
      prompt: { content: USER_MSG.content, id: 'm1', role: 'user' },
      threadId: 'thread-1',
      responseId: 'resp-1',
    })
  })

  it('sends only the LAST user message, not the history', async () => {
    // Full history lives in the backend checkpointer; re-sending it would
    // duplicate every turn.
    await call([
      { id: 'm0', role: 'user', content: 'older question' },
      { id: 'm0a', role: 'assistant', content: 'older answer' },
      USER_MSG,
    ])
    expect(JSON.parse(authedFetch.mock.calls[0][1].body).prompt.id).toBe('m1')
  })

  it('throws when there is no user message to send', async () => {
    await expect(call([{ id: 'a1', role: 'assistant', content: 'hi' }])).rejects.toThrow()
    expect(authedFetch).not.toHaveBeenCalled()
  })

  it('passes the abort signal through', async () => {
    await call([USER_MSG])
    expect(authedFetch.mock.calls[0][1].signal).toBeInstanceOf(AbortSignal)
  })
})

describe('chatProcessMessage — rate limiting', () => {
  it('turns a 429 into a readable 200 so the chat UI can render it', async () => {
    authedFetch.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Too many enquiries. Please try again in 5 minutes.' }),
        { status: 429, headers: { 'Content-Type': 'application/json' } })
    )
    const res = await call([USER_MSG])
    expect(res.status).toBe(200)
    expect(await res.text()).toBe('_Too many enquiries. Please try again in 5 minutes._')
  })

  it('falls back to a generic message when the 429 body is not JSON', async () => {
    authedFetch.mockResolvedValue(new Response('<html>rate limited</html>', { status: 429 }))
    const res = await call([USER_MSG])
    expect(res.status).toBe(200)
    expect(await res.text()).toContain('Too many enquiries')
  })

  it('passes other responses straight through', async () => {
    const upstream = new Response('stream', { status: 200 })
    authedFetch.mockResolvedValue(upstream)
    expect(await call([USER_MSG])).toBe(upstream)
  })

  it('does not swallow a 500 — it must reach the chat UI as an error', async () => {
    authedFetch.mockResolvedValue(new Response('boom', { status: 500 }))
    expect((await call([USER_MSG])).status).toBe(500)
  })
})
