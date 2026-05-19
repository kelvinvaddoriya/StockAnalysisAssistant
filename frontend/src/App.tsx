import { useState, useEffect, lazy, Suspense } from 'react'
import { ThemeProvider } from '@thesysai/genui-sdk'
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
      <ThemeProvider mode='dark'>
        <div className='loading-screen'>
          <div className='loading-brand'>
            <svg viewBox="0 0 32 32" width="28" height="28">
              <circle cx="16" cy="16" r="14" fill="none" stroke="currentColor" strokeWidth="1" />
              <path d="M9 22 L 9 10 L 16 18 L 23 10 L 23 22" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div>
              <div className='loading-brand-word'>Bourse</div>
              <div className='loading-sub'>Preparing your briefing…</div>
            </div>
          </div>
        </div>
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider mode='dark'>
      {user ? (
        <Suspense fallback={
          <div className='loading-screen'>
            <div className='loading-brand'>
              <svg viewBox="0 0 32 32" width="28" height="28">
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
    </ThemeProvider>
  )
}

export default App
