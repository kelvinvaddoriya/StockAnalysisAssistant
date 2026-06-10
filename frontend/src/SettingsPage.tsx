import { useRef, useState } from 'react'
import { supabase } from './supabase'

interface Props {
  user: { email: string; id: string }
  displayName: string
  avatarUrl: string
  onSave: (displayName: string, avatarUrl: string) => void
}

function getInitials(name: string, email: string) {
  if (name.trim()) {
    return name.trim().split(/\s+/).map(p => p[0]?.toUpperCase() ?? '').slice(0, 2).join('')
  }
  return email[0]?.toUpperCase() ?? '?'
}

// Raster formats only — SVG can embed script, and anything else bloats
// localStorage. Keep in sync with the "JPG, PNG, WebP" hint below.
const ALLOWED_AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp']
const MAX_AVATAR_BYTES = 2 * 1024 * 1024

export default function SettingsPage({ user, displayName: initialName, avatarUrl: initialAvatar, onSave }: Props) {
  const [name, setName] = useState(initialName)
  const [avatar, setAvatar] = useState(initialAvatar)
  const [avatarError, setAvatarError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!ALLOWED_AVATAR_TYPES.includes(file.type)) {
      setAvatarError('Please choose a JPG, PNG or WebP image.')
      return
    }
    if (file.size > MAX_AVATAR_BYTES) {
      setAvatarError('Image is too large — 2 MB max.')
      return
    }
    setAvatarError('')
    const reader = new FileReader()
    reader.onload = ev => setAvatar(ev.target?.result as string)
    reader.readAsDataURL(file)
  }

  function removeAvatar() {
    setAvatar('')
    setAvatarError('')
  }

  async function handleSave() {
    setSaving(true)
    await supabase.auth.updateUser({ data: { display_name: name.trim() } })
    if (avatar) {
      localStorage.setItem(`bourse-avatar-${user.id}`, avatar)
    } else {
      localStorage.removeItem(`bourse-avatar-${user.id}`)
    }
    onSave(name.trim(), avatar)
    setSaving(false)
    setSaved(true)
    setTimeout(() => setSaved(false), 2200)
  }

  const initials = getInitials(name, user.email)

  return (
    <div className="settings-page">
      <div className="settings-body">

        {/* ── Profile ── */}
        <section className="settings-section">
          <div className="settings-section-label">Profile</div>

          <div className="settings-avatar-row">
            <div className="settings-avatar-wrap">
              <button className="settings-avatar-btn" onClick={() => fileRef.current?.click()} title="Upload photo">
                {avatar
                  ? <img src={avatar} alt="Profile" className="settings-avatar-img" />
                  : <span className="settings-avatar-initials">{initials}</span>
                }
                <div className="settings-avatar-overlay">
                  <svg viewBox="0 0 20 20" width="15" height="15" fill="none">
                    <path d="M13 3H7L5 6H3a1 1 0 0 0-1 1v9a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1V7a1 1 0 0 0-1-1h-2L13 3z" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round"/>
                    <circle cx="10" cy="11" r="2.5" stroke="currentColor" strokeWidth="1.3"/>
                  </svg>
                </div>
              </button>
              <input ref={fileRef} type="file" accept="image/*" onChange={handleFileChange} style={{ display: 'none' }} />
            </div>
            <div className="settings-avatar-meta">
              <div className="settings-avatar-name">{name || user.email}</div>
              <div className="settings-avatar-sub">Click to upload · JPG, PNG, WebP</div>
              {avatarError && (
                <div className="settings-avatar-sub" role="alert" style={{ color: 'var(--down, #e8333a)' }}>
                  {avatarError}
                </div>
              )}
              {avatar && (
                <button className="settings-avatar-remove" onClick={removeAvatar}>Remove photo</button>
              )}
            </div>
          </div>

          <div className="settings-field">
            <label className="settings-label">Display name</label>
            <input
              className="settings-input"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Your name"
              maxLength={64}
              onKeyDown={e => e.key === 'Enter' && handleSave()}
            />
          </div>

          <div className="settings-field">
            <label className="settings-label">Email</label>
            <input className="settings-input settings-input-readonly" value={user.email} readOnly />
          </div>

          <button
            className={`settings-save${saved ? ' saved' : ''}`}
            onClick={handleSave}
            disabled={saving || saved}
          >
            {saved ? '✓  Saved' : saving ? 'Saving…' : 'Save changes'}
          </button>
        </section>

        {/* ── How to use ── */}
        <section className="settings-section">
          <div className="settings-section-label">How to use Bourse</div>

          <div className="guide-grid">
            <div className="guide-step">
              <div className="guide-num">01</div>
              <div className="guide-content">
                <div className="guide-heading">Ask anything about a stock</div>
                <div className="guide-body">
                  Type a company name, ticker, or plain-English question — e.g. "What is Apple's current P/E?" or
                  "Summarise TSLA's last earnings call." Bourse pulls live data and explains it clearly.
                </div>
              </div>
            </div>

            <div className="guide-step">
              <div className="guide-num">02</div>
              <div className="guide-content">
                <div className="guide-heading">Browse past enquiries</div>
                <div className="guide-body">
                  Every conversation is saved automatically. Open the sidebar and click any title to
                  review the full exchange, including charts and data tables.
                </div>
              </div>
            </div>

            <div className="guide-step">
              <div className="guide-num">03</div>
              <div className="guide-content">
                <div className="guide-heading">Start a new enquiry</div>
                <div className="guide-body">
                  Press the red "New enquiry" button at the top of the sidebar to open a fresh
                  session. Each enquiry is stored independently so you can return to any of them later.
                </div>
              </div>
            </div>

            <div className="guide-step">
              <div className="guide-num">04</div>
              <div className="guide-content">
                <div className="guide-heading">Switch themes</div>
                <div className="guide-body">
                  Use the sun / moon icon in the top-right corner to toggle between dark and light
                  mode. Your preference is saved in the browser and restored on every visit.
                </div>
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
