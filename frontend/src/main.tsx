import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App.tsx'

// apply saved theme before first paint to avoid flash
const saved = localStorage.getItem('bourse-theme')
if (saved === 'light') document.documentElement.setAttribute('data-theme', 'light')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
