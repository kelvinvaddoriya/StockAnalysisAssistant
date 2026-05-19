import { useState } from 'react'
import { supabase } from './supabase'

export default function LoginPage() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (mode === 'register') {
        const { error } = await supabase.auth.signUp({ email, password })
        if (error) setError(error.message)
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password })
        if (error) setError(error.message)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg.includes('fetch') || msg.includes('network') || msg.includes('Failed')) {
        setError('Cannot reach Supabase — project may be paused. Check your Supabase dashboard.')
      } else {
        setError(msg || 'Something went wrong')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-bg">
      <div className="auth-card">
        <div className="auth-brand">
          <svg viewBox="0 0 32 32" width="26" height="26">
            <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" />
            <path
              d="M9 22 L 9 10 L 16 18 L 23 10 L 23 22"
              fill="none" stroke="currentColor" strokeWidth="1.4"
              strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
          <div>
            <div className="auth-brand-word">Bourse</div>
            <span className="auth-brand-tag">equity briefing</span>
          </div>
        </div>

        <div className="auth-tabs">
          <button
            className={`auth-tab${mode === 'login' ? ' active' : ''}`}
            onClick={() => { setMode('login'); setError('') }}
          >
            Sign In
          </button>
          <button
            className={`auth-tab${mode === 'register' ? ' active' : ''}`}
            onClick={() => { setMode('register'); setError('') }}
          >
            Register
          </button>
        </div>

        <form onSubmit={handleSubmit} className="auth-form">
          <input
            type="email"
            placeholder="Email address"
            value={email}
            onChange={e => setEmail(e.target.value)}
            className="auth-input"
            required
            autoFocus
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="auth-input"
            required
          />
          {error && <p className="auth-error">{error}</p>}
          <button type="submit" className="auth-btn" disabled={loading}>
            {loading ? 'Please wait…' : mode === 'login' ? 'Sign In' : 'Create Account'}
          </button>
        </form>
      </div>
    </div>
  )
}
