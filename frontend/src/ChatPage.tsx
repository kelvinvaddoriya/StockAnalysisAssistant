import { useState, useEffect, useCallback } from 'react'
import { C1Chat } from '@thesysai/genui-sdk'

interface User {
  email: string
  id: string
}

interface Thread {
  thread_id: string
  title: string
  updated_at: string
}

interface Message {
  role: 'user' | 'assistant'
  content: string
}

interface Props {
  user: User
  onLogout: () => void
}

export default function ChatPage({ user, onLogout }: Props) {
  const [threads, setThreads] = useState<Thread[]>([])
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [threadMessages, setThreadMessages] = useState<Message[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [fetchError, setFetchError] = useState('')
  const [chatKey, setChatKey] = useState(0)

  const fetchThreads = useCallback(async () => {
    const res = await fetch('/api/chats')
    if (res.ok) setThreads(await res.json())
  }, [])

  useEffect(() => {
    fetchThreads()
    const id = setInterval(fetchThreads, 8000)
    return () => clearInterval(id)
  }, [fetchThreads])

  async function openThread(thread: Thread) {
    setLoadingMessages(true)
    setFetchError('')
    setSelectedThread(thread)
    try {
      const res = await fetch(`/api/chats/${thread.thread_id}`)
      if (res.ok) {
        setThreadMessages(await res.json())
      } else {
        const err = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        setFetchError(err.detail ?? `HTTP ${res.status}`)
      }
    } catch (e) {
      setFetchError('Network error loading messages')
    }
    setLoadingMessages(false)
  }

  function closeThread() {
    setSelectedThread(null)
    setThreadMessages([])
  }

  async function handleLogout() {
    await fetch('/api/auth/logout', { method: 'POST' })
    onLogout()
  }

  function newChat() {
    closeThread()
    setChatKey(k => k + 1)
    setTimeout(fetchThreads, 1000)
  }

  return (
    <div className='chat-layout'>
      <aside className='sidebar'>
        <div className='sidebar-header'>
          <span className='sidebar-logo'>StockAI</span>
        </div>

        <button className='new-chat-btn' onClick={newChat}>
          + New Chat
        </button>

        <div className='thread-list'>
          {threads.map(t => (
            <button
              key={t.thread_id}
              className={`thread-item ${selectedThread?.thread_id === t.thread_id ? 'active' : ''}`}
              onClick={() => openThread(t)}
            >
              <span className='thread-title'>{t.title}</span>
              <span className='thread-date'>{formatDate(t.updated_at)}</span>
            </button>
          ))}
          {threads.length === 0 && (
            <p className='no-threads'>No past chats yet</p>
          )}
        </div>

        <div className='sidebar-footer'>
          <span className='user-email' title={user.email}>{user.email}</span>
          <button className='logout-btn' onClick={handleLogout}>Logout</button>
        </div>
      </aside>

      <main className='chat-main'>
        {selectedThread ? (
          <div className='thread-view'>
            <div className='thread-view-header'>
              <span className='thread-view-title'>{selectedThread.title}</span>
              <button className='close-btn' onClick={closeThread}>✕ Close</button>
            </div>
            <div className='messages-list'>
              {loadingMessages && <p className='loading-msgs'>Loading…</p>}
              {fetchError && <p className='loading-msgs' style={{color:'#ff6b6b'}}>{fetchError}</p>}
              {threadMessages.map((msg, i) => (
                <div key={i} className={`message message-${msg.role}`}>
                  <div className='message-bubble'>{msg.content}</div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <C1Chat key={chatKey} apiUrl='/api/chat' />
        )}
      </main>
    </div>
  )
}


function formatDate(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}
