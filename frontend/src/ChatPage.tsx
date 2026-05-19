import { useState, useEffect, useCallback } from 'react'
import { C1Chat } from '@thesysai/genui-sdk'
import { supabase } from './supabase'

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

function formatDate(iso: string) {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

function getInitials(email: string) {
  const name = email.split('@')[0]
  const parts = name.split(/[._-]/)
  return parts.slice(0, 2).map(p => p[0]?.toUpperCase() ?? '').join('') || email[0]?.toUpperCase() || '?'
}

function MarketStatus() {
  const now = new Date()
  const et = new Date(now.toLocaleString('en-US', { timeZone: 'America/New_York' }))
  const day = et.getDay()
  const mins = et.getHours() * 60 + et.getMinutes()
  const isOpen = day >= 1 && day <= 5 && mins >= 570 && mins < 960

  return (
    <div className="market-status">
      <span className={`ms-dot${isOpen ? ' open' : ''}`} />
      <span>{isOpen ? 'Markets open' : 'Markets closed'}</span>
    </div>
  )
}

export default function ChatPage({ user, onLogout }: Props) {
  const [threads, setThreads] = useState<Thread[]>([])
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [threadMessages, setThreadMessages] = useState<Message[]>([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [fetchError, setFetchError] = useState('')
  const [chatKey, setChatKey] = useState(0)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 1280)

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
    } catch {
      setFetchError('Network error loading messages')
    }
    setLoadingMessages(false)
  }

  function closeThread() {
    setSelectedThread(null)
    setThreadMessages([])
    setFetchError('')
  }

  function newChat() {
    closeThread()
    setChatKey(k => k + 1)
    setTimeout(fetchThreads, 1000)
  }

  async function handleLogout() {
    await supabase.auth.signOut()
    onLogout()
  }

  const initials = getInitials(user.email)
  const threadTitle = selectedThread?.title ?? 'New enquiry'

  return (
    <div className={`app${sidebarOpen ? '' : ' sidebar-collapsed'}`}>

      {/* SIDEBAR */}
      <aside className={`sidebar${sidebarOpen ? ' open' : ' closed'}`}>
        <div className="brand">
          <div className="brand-mark">
            <svg viewBox="0 0 32 32" width="22" height="22">
              <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" />
              <path
                d="M9 22 L 9 10 L 16 18 L 23 10 L 23 22"
                fill="none" stroke="currentColor" strokeWidth="1.4"
                strokeLinecap="round" strokeLinejoin="round"
              />
            </svg>
          </div>
          <div className="brand-name">
            <div className="brand-word">Bourse</div>
            <div className="brand-tag">est.2025</div>
          </div>
        </div>

        <button className="new-chat" onClick={newChat}>
          <span className="plus">+</span> New enquiry
        </button>

        <div className="side-section">
          <div className="side-label">Recent enquiries</div>
          <ul className="hist">
            {threads.length === 0 && (
              <li className="hist-empty">No past enquiries yet</li>
            )}
            {threads.map(t => (
              <li
                key={t.thread_id}
                className={`hist-item${selectedThread?.thread_id === t.thread_id ? ' active' : ''}`}
                onClick={() => openThread(t)}
              >
                <span className="hist-title">{t.title}</span>
                <span className="hist-time">{formatDate(t.updated_at)}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="side-foot">
          <MarketStatus />
          <div className="user-row">
            <div className="avatar">{initials}</div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div className="user-name">{user.email}</div>
              <div className="user-plan">Equity research · Pro</div>
            </div>
            <button className="logout-small" onClick={handleLogout} title="Sign out">↩</button>
          </div>
        </div>
      </aside>

      {/* MAIN */}
      <main className="main">
        <header className="topbar">
          <button
            className="icon-btn"
            onClick={() => setSidebarOpen(s => !s)}
            aria-label="Toggle sidebar"
          >
            <svg viewBox="0 0 20 20" width="18" height="18">
              <path d="M3 5h14M3 10h14M3 15h14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
            </svg>
          </button>

          <div className="thread-title">
            <span className="thread-eyebrow">Enquiry</span>
            <h1>{threadTitle}</h1>
          </div>

          <div className="top-actions">
            {selectedThread && (
              <button className="rbtn rbtn-ghost" onClick={closeThread}>
                ← New enquiry
              </button>
            )}
          </div>
        </header>

        {selectedThread ? (
          <div className="conversation">
            {loadingMessages && (
              <p className="msg-loading">Loading briefing…</p>
            )}
            {fetchError && (
              <p className="msg-error">{fetchError}</p>
            )}
            {threadMessages.map((msg, i) =>
              msg.role === 'user' ? (
                <div key={i} className="msg msg-user">
                  <div className="msg-byline">You</div>
                  <div className="msg-body">{msg.content}</div>
                </div>
              ) : (
                <div key={i} className="msg msg-assistant">
                  <div className="msg-byline">
                    <span className="assistant-mark" /> Bourse
                  </div>
                  <div className="msg-body">
                    <p className="lede">{msg.content}</p>
                  </div>
                </div>
              )
            )}
          </div>
        ) : (
          <div className="c1chat-wrap">
            <C1Chat key={chatKey} apiUrl="/api/chat" />
          </div>
        )}
      </main>
    </div>
  )
}
