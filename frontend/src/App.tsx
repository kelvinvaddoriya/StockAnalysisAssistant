import { useState, useEffect, lazy, Suspense } from 'react'
import { Analytics } from '@vercel/analytics/react'
// Crayon's stylesheet stays here, ahead of App.css, so the overrides in App.css
// keep winning the cascade. The SDK's JS (ThemeProvider, C1Chat) is only
// imported from ChatPage — pulling it in here put the whole SDK, ~3 MB, into
// the bundle every visitor downloads just to see the login form.
import '@crayonai/react-ui/styles/index.css'
import './App.css'
import LoginPage from './LoginPage'
import { supabase } from './supabase'
import type { User } from '@supabase/supabase-js'

const ChatPage = lazy(() => import('./ChatPage'))

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null)
      setChecking(false)
    })

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null)
    })

    return () => subscription.unsubscribe()
  }, [])

  if (checking) {
    return (
      <div className='loading-screen'>
        <div className='loading-brand'>
          <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
            <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" />
            <path d="M9 22 L 9 10 L 16 18 L 23 10 L 23 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          <div>
            <div className='loading-brand-word'>Bourse</div>
            <div className='loading-sub'>Preparing your briefing…</div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <>
      {user ? (
        <Suspense fallback={
          <div className='loading-screen'>
            <div className='loading-brand'>
              <svg viewBox="0 0 32 32" width="28" height="28" aria-hidden="true">
                <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" />
                <path d="M9 22 L 9 10 L 16 18 L 23 10 L 23 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <div>
                <div className='loading-brand-word'>Bourse</div>
                <div className='loading-sub'>Loading…</div>
              </div>
            </div>
          </div>
        }>
          <ChatPage
            user={{ email: user.email ?? '', id: user.id }}
            onLogout={() => supabase.auth.signOut()}
          />
        </Suspense>
      ) : (
        <LoginPage />
      )}
      <Analytics />
    </>
  )
}

export default App
