import { useState, useEffect } from 'react'
import { ThemeProvider } from '@thesysai/genui-sdk'
import '@crayonai/react-ui/styles/index.css'
import './App.css'
import LoginPage from './LoginPage'
import ChatPage from './ChatPage'
import { supabase } from './supabase'
import type { User } from '@supabase/supabase-js'

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
        <div className='loading-screen'>Loading…</div>
      </ThemeProvider>
    )
  }

  return (
    <ThemeProvider mode='dark'>
      {user ? (
        <ChatPage
          user={{ email: user.email ?? '', id: user.id }}
          onLogout={() => supabase.auth.signOut()}
        />
      ) : (
        <LoginPage />
      )}
    </ThemeProvider>
  )
}

export default App
