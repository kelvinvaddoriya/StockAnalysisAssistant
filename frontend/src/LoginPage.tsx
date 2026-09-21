import { useState } from 'react'
import { supabase } from './supabase'
import Turnstile, { TURNSTILE_ENABLED } from './Turnstile'

type Mode = 'login' | 'register'

// Set after any successful sign-in or sign-up. A first-time visitor lands on
// "Create account"; a returning one lands on "Sign in". Either way there is one
// primary button.
const RETURNING_KEY = 'bourse-returning'

function isReturning(): boolean {
  try { return localStorage.getItem(RETURNING_KEY) === '1' } catch { return false }
}
function markReturning() {
  try { localStorage.setItem(RETURNING_KEY, '1') } catch { /* private mode */ }
}

const MIN_PASSWORD = 8

export default function LoginPage() {
  const [mode, setMode] = useState<Mode>(() => (isReturning() ? 'login' : 'register'))
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [loading, setLoading] = useState(false)
  const [captchaToken, setCaptchaToken] = useState('')
  // Turnstile tokens are single-use; bumping this remounts the widget for a fresh one.
  const [captchaKey, setCaptchaKey] = useState(0)

  function switchMode(next: Mode) {
    setMode(next)
    setError('')
    setSuccess('')
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setSuccess('')

    const cleanEmail = email.trim()
    if (mode === 'register' && password.length < MIN_PASSWORD) {
      setError(`Password must be at least ${MIN_PASSWORD} characters.`)
      return
    }
    if (TURNSTILE_ENABLED && !captchaToken) {
      setError('Please complete the verification check.')
      return
    }

    setLoading(true)
    const options = TURNSTILE_ENABLED ? { captchaToken } : undefined
    try {
      if (mode === 'register') {
        const { data, error } = await supabase.auth.signUp({ email: cleanEmail, password, options })
        if (error) {
          setError(error.message)
        } else {
          markReturning()
          if (data.user && !data.session) {
            // Supabase project has email confirmation enabled — user must verify
            // before they can sign in. Switch mode so the next action is clear.
            setSuccess(`Account created. Check ${cleanEmail} for a confirmation link, then sign in.`)
            setPassword('')
            setMode('login')
          }
        }
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email: cleanEmail, password, options })
        if (error) setError(error.message)
        else markReturning()
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
      if (TURNSTILE_ENABLED) {
        setCaptchaToken('')
        setCaptchaKey(k => k + 1)
      }
    }
  }

  const isRegister = mode === 'register'

  return (
    <div className="auth-bg">
      <main className="auth-card">
        <div className="auth-brand">
          <svg viewBox="0 0 32 32" width="26" height="26" aria-hidden="true">
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

        <h1 className="auth-headline">Ask about any stock in plain English.</h1>
        <p className="auth-pitch">
          An AI analyst desk pulls live prices, fundamentals and news, then gives you one clear briefing with charts.
        </p>

        <form onSubmit={handleSubmit} className="auth-form">
          <label className="sr-only" htmlFor="auth-email">Email address</label>
          <input
            id="auth-email"
            type="email"
            placeholder="Email address"
            value={email}
            onChange={e => setEmail(e.target.value)}
            className="auth-input"
            autoComplete="email"
            maxLength={254}
            required
            autoFocus
          />
          <label className="sr-only" htmlFor="auth-password">Password</label>
          <input
            id="auth-password"
            type="password"
            placeholder={isRegister ? `Password (min. ${MIN_PASSWORD} characters)` : 'Password'}
            value={password}
            onChange={e => setPassword(e.target.value)}
            className="auth-input"
            autoComplete={isRegister ? 'new-password' : 'current-password'}
            minLength={isRegister ? MIN_PASSWORD : undefined}
            maxLength={72}
            required
            aria-describedby={error ? 'auth-error' : undefined}
          />

          {TURNSTILE_ENABLED && <Turnstile key={captchaKey} onToken={setCaptchaToken} />}

          <div aria-live="polite">
            {success && <p className="auth-success">{success}</p>}
            {error && <p className="auth-error" id="auth-error">{error}</p>}
          </div>

          <button type="submit" className="auth-btn" disabled={loading}>
            {loading ? 'Please wait…' : isRegister ? 'Create free account' : 'Sign in'}
          </button>
        </form>

        <p className="auth-switch">
          {isRegister ? 'Already have an account?' : 'New to Bourse?'}{' '}
          <button type="button" className="auth-link" onClick={() => switchMode(isRegister ? 'login' : 'register')}>
            {isRegister ? 'Sign in' : 'Create an account'}
          </button>
        </p>

        <p className="auth-legal">
          {isRegister && <>By creating an account you agree to the <a href="/terms">Terms</a> and <a href="/privacy">Privacy Policy</a>. </>}
          For information only, not investment advice.
          {!isRegister && <> <a href="/terms">Terms</a> · <a href="/privacy">Privacy</a></>}
        </p>
      </main>
    </div>
  )
}
