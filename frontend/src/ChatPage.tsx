import { useState, useEffect, useCallback } from 'react'
import { C1Chat, useThreadListManager, useThreadManager } from '@thesysai/genui-sdk'
import { supabase } from './supabase'
import SettingsPage from './SettingsPage'
import { formatDate, getInitials, profileInitials } from './utils'

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

// ── SparklineLoader ───────────────────────────────────────────────────────────

const HEADLINES = [
  'Analysing market data…',
  'Cross-referencing financials…',
  'Pulling live quotes…',
  'Drafting your briefing…',
]

function SparklineLoader() {
  const [pts, setPts] = useState<number[]>(() =>
    Array.from({ length: 32 }, (_, i) => 40 + Math.sin(i / 3) * 10)
  )
  const [hlIdx, setHlIdx] = useState(0)

  useEffect(() => {
    let v = 50
    const dataTick = setInterval(() => {
      v = Math.max(10, Math.min(90, v + (Math.random() - 0.4) * 12))
      setPts(p => [...p.slice(1), v])
    }, 130)
    const hlTick = setInterval(() => setHlIdx(i => (i + 1) % HEADLINES.length), 1800)
    return () => { clearInterval(dataTick); clearInterval(hlTick) }
  }, [])

  const W = 280, H = 52
  const path = pts
    .map((y, i) => `${i === 0 ? 'M' : 'L'} ${(i / (pts.length - 1)) * W} ${H - (y / 100) * H}`)
    .join(' ')
  const last = pts[pts.length - 1]
  const first = pts[0]
  const delta = Math.abs(((last - first) / first) * 100).toFixed(2)
  const up = last >= first

  return (
    <div className="chat-row chat-row-assistant sl-loader">
      <div className="chat-avatar">B</div>
      <div className="chat-assistant-body">
        <div className="chat-label">Bourse</div>
        <div className="sl-bubble">
          {/* rotating headline */}
          <div className="sl-headline-row">
            <span className="sl-spinner" />
            <span className="sl-headline" key={hlIdx}>{HEADLINES[hlIdx]}</span>
          </div>

          {/* sparkline card */}
          <div className="sl-card">
            <div className="sl-card-header">
              <span className="sl-sym">LIVE</span>
              <span className="sl-chg" style={{ color: up ? 'var(--up)' : 'var(--down)' }}>
                {up ? '↑' : '↓'} {delta}%
              </span>
              <span className="sl-streaming">· STREAMING</span>
            </div>

            <svg
              viewBox={`0 0 ${W} ${H}`}
              preserveAspectRatio="none"
              style={{ width: '100%', height: H, display: 'block' }}
            >
              <defs>
                <linearGradient id="sl-grad" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor={up ? '#00c97a' : '#e8333a'} stopOpacity="0.22" />
                  <stop offset="100%" stopColor={up ? '#00c97a' : '#e8333a'} stopOpacity="0" />
                </linearGradient>
              </defs>
              <path d={`${path} L ${W} ${H} L 0 ${H} Z`} fill="url(#sl-grad)" />
              <path d={path} fill="none" stroke={up ? '#00c97a' : '#e8333a'} strokeWidth="1.5" strokeLinejoin="round" />
              <circle cx={W} cy={H - (last / 100) * H} r="3" fill={up ? '#00c97a' : '#e8333a'}>
                <animate attributeName="r" values="3;5;3" dur="1.1s" repeatCount="indefinite" />
              </circle>
            </svg>

            {/* skeleton lines — answer being drafted */}
            <div className="sl-skel" />
            <div className="sl-skel" style={{ width: '74%' }} />
            <div className="sl-skel" style={{ width: '44%' }} />
          </div>
        </div>
      </div>
    </div>
  )
}

// ── ContinuationChat: loads an existing thread AND allows sending new messages ──

function ContinuationChat({ thread }: { thread: Thread }) {
  const [loading, setLoading] = useState(true)

  const threadListManager = useThreadListManager({
    fetchThreadList: async () => [{ id: thread.thread_id, title: thread.title }],
    createThread: async () => ({ id: crypto.randomUUID(), title: 'New Enquiry' }),
    deleteThread: async () => {},
    updateThread: async (t) => t,
    onSwitchToNew: () => {},
    onSelectThread: () => {},
  })

  const threadManager = useThreadManager({
    threadListManager,
    loadThread: async (tid) => {
      const res = await fetch(`/api/chats/${tid}`)
      if (!res.ok) { setLoading(false); return [] }
      const rows: { role: string; content: string }[] = await res.json()
      setLoading(false)
      return rows.map((m, i) => ({
        id: `${tid}-${i}`,
        role: m.role as 'user' | 'assistant',
        content: m.content,
      }))
    },
    apiUrl: '/api/chat',
  })

  useEffect(() => {
    threadListManager.selectThread(thread.thread_id)
  }, [thread.thread_id]) // eslint-disable-line react-hooks/exhaustive-deps

  if (loading) {
    return (
      <div className="conversation">
        <SparklineLoader />
      </div>
    )
  }

  return <C1Chat threadManager={threadManager} agentName="Bourse" />
}

// ── DeleteModal ───────────────────────────────────────────────────────────────

function DeleteModal({
  title,
  onConfirm,
  onCancel,
}: {
  title: string
  onConfirm: () => void
  onCancel: () => void
}) {
  return (
    <div className="del-overlay" onClick={onCancel}>
      <div className="del-modal" onClick={e => e.stopPropagation()}>
        <div className="del-icon">
          <svg viewBox="0 0 24 24" width="26" height="26" fill="none">
            <path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M10 11v5M14 11v5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
        </div>
        <div className="del-body">
          <p className="del-heading">Delete enquiry</p>
          <p className="del-sub">
            <span className="del-name">"{title}"</span> will be permanently removed.
            This cannot be undone.
          </p>
        </div>
        <div className="del-actions">
          <button className="del-btn del-btn-cancel" onClick={onCancel}>Cancel</button>
          <button className="del-btn del-btn-confirm" onClick={onConfirm}>Delete</button>
        </div>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────

type View = 'chat' | 'settings'

export default function ChatPage({ user, onLogout }: Props) {
  const [threads, setThreads] = useState<Thread[]>([])
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null)
  const [chatKey, setChatKey] = useState(0)
  const [sidebarOpen, setSidebarOpen] = useState(() => window.innerWidth > 1280)
  const [view, setView] = useState<View>('chat')
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    return (localStorage.getItem('bourse-theme') as 'dark' | 'light') ?? 'dark'
  })
  const [displayName, setDisplayName] = useState('')
  const [avatarUrl, setAvatarUrl] = useState('')
  const [pendingDelete, setPendingDelete] = useState<Thread | null>(null)

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    localStorage.setItem('bourse-theme', theme)
  }, [theme])

  // load saved display name and avatar on mount
  useEffect(() => {
    supabase.auth.getUser().then(({ data }) => {
      setDisplayName(data.user?.user_metadata?.display_name ?? '')
    })
    const saved = localStorage.getItem(`bourse-avatar-${user.id}`)
    if (saved) setAvatarUrl(saved)
  }, [user.id])

  function toggleTheme() {
    setTheme(t => t === 'dark' ? 'light' : 'dark')
  }

  const fetchThreads = useCallback(async () => {
    const res = await fetch('/api/chats')
    if (res.ok) setThreads(await res.json())
  }, [])

  useEffect(() => {
    fetchThreads()
    const id = setInterval(fetchThreads, 8000)
    return () => clearInterval(id)
  }, [fetchThreads])

  function openThread(thread: Thread) {
    setView('chat')
    setSelectedThread(thread)
  }

  function closeThread() {
    setSelectedThread(null)
  }

  function deleteThread(e: React.MouseEvent, thread: Thread) {
    e.stopPropagation()
    setPendingDelete(thread)
  }

  async function confirmDelete() {
    if (!pendingDelete) return
    await fetch(`/api/chats/${pendingDelete.thread_id}`, { method: 'DELETE' })
    setThreads(prev => prev.filter(t => t.thread_id !== pendingDelete.thread_id))
    if (selectedThread?.thread_id === pendingDelete.thread_id) closeThread()
    setPendingDelete(null)
  }

  function newChat() {
    setView('chat')
    closeThread()
    setChatKey(k => k + 1)
    setTimeout(fetchThreads, 1000)
  }

  async function handleLogout() {
    await supabase.auth.signOut()
    onLogout()
  }

  function handleProfileSave(name: string, avatar: string) {
    setDisplayName(name)
    setAvatarUrl(avatar)
  }

  const initials = profileInitials(displayName, user.email)
  const threadTitle = selectedThread?.title ?? 'New enquiry'
  const topbarEyebrow = view === 'settings' ? 'Account' : 'Enquiry'
  const topbarTitle   = view === 'settings' ? 'Settings' : threadTitle

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
                <button
                  className="hist-delete"
                  onClick={(e) => deleteThread(e, t)}
                  title="Delete enquiry"
                >
                  <svg viewBox="0 0 16 16" width="13" height="13" fill="none">
                    <path d="M2 4h12M6 4V2.5h4V4M13 4l-.75 9.5H3.75L3 4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round"/>
                    <path d="M6.5 7.5v4M9.5 7.5v4" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round"/>
                  </svg>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="side-foot">
          <MarketStatus />
          <div className="user-row">
            <button className="user-row-main" onClick={() => setView('settings')}>
              <div className="avatar">
                {avatarUrl
                  ? <img src={avatarUrl} alt="Profile" className="avatar-img" />
                  : initials
                }
              </div>
              <div className="user-row-text">
                <div className="user-name">{displayName || user.email}</div>
                <div className="user-plan">Equity research · Pro</div>
              </div>
            </button>
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
            <span className="thread-eyebrow">{topbarEyebrow}</span>
            <h1>{topbarTitle}</h1>
          </div>

          <div className="top-actions">
            {view === 'settings' ? (
              <button className="rbtn rbtn-ghost" onClick={() => setView('chat')}>
                ← Back
              </button>
            ) : selectedThread ? (
              <button className="rbtn rbtn-ghost" onClick={closeThread}>
                ← New enquiry
              </button>
            ) : null}
            <button className="theme-toggle" onClick={toggleTheme} aria-label="Toggle theme" title={theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}>
              {theme === 'dark' ? (
                <svg viewBox="0 0 20 20" width="15" height="15" fill="none">
                  <circle cx="10" cy="10" r="4" stroke="currentColor" strokeWidth="1.4" />
                  <path d="M10 2v2M10 16v2M2 10h2M16 10h2M4.22 4.22l1.42 1.42M14.36 14.36l1.42 1.42M4.22 15.78l1.42-1.42M14.36 5.64l1.42-1.42" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
                </svg>
              ) : (
                <svg viewBox="0 0 20 20" width="15" height="15" fill="none">
                  <path d="M17 11.5A7 7 0 1 1 8.5 3a5.5 5.5 0 0 0 8.5 8.5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" />
                </svg>
              )}
            </button>
          </div>
        </header>

        {view === 'settings' ? (
          <SettingsPage
            user={user}
            displayName={displayName}
            avatarUrl={avatarUrl}
            onSave={handleProfileSave}
          />
        ) : selectedThread ? (
          <div className="c1chat-wrap">
            <ContinuationChat key={selectedThread.thread_id} thread={selectedThread} />
          </div>
        ) : (
          <div className="c1chat-wrap">
            <C1Chat key={chatKey} apiUrl="/api/chat" />
          </div>
        )}
      </main>

      {pendingDelete && (
        <DeleteModal
          title={pendingDelete.title}
          onConfirm={confirmDelete}
          onCancel={() => setPendingDelete(null)}
        />
      )}
    </div>
  )
}
