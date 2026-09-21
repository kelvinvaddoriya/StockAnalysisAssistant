import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
// Self-hosted rather than Google Fonts: no third-party request (which would hand
// every visitor's IP to Google), and one less origin to connect to on first load.
import '@fontsource-variable/inter'
import '@fontsource-variable/inter-tight'
import App from './App.tsx'

// apply saved theme before first paint to avoid flash
const saved = localStorage.getItem('bourse-theme')
if (saved === 'light') document.documentElement.setAttribute('data-theme', 'light')

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
