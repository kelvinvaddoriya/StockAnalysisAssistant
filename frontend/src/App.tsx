import { useState, useEffect } from 'react'
import { ThemeProvider } from '@thesysai/genui-sdk'
import '@crayonai/react-ui/styles/index.css'
import './App.css'
import LoginPage from './LoginPage'
import ChatPage from './ChatPage'

interface User {
  email: string
  id: string
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    fetch('/api/auth/me')
      .then(r => (r.ok ? r.json() : null))
      .then(data => { setUser(data); setChecking(false) })
      .catch(() => setChecking(false))
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
        <ChatPage user={user} onLogout={() => setUser(null)} />
      ) : (
        <LoginPage onLogin={setUser} />
      )}
    </ThemeProvider>
  )
}

export default App
