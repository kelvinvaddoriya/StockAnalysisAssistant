export function formatDate(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return 'Just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 7) return `${days}d ago`
  return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
}

export function getInitials(email: string): string {
  const name = email.split('@')[0]
  const parts = name.split(/[._-]/)
  return parts.slice(0, 2).map(p => p[0]?.toUpperCase() ?? '').join('') || email[0]?.toUpperCase() || '?'
}

export function profileInitials(displayName: string, email: string): string {
  if (displayName.trim()) {
    return displayName.trim().split(/\s+/).map(p => p[0]?.toUpperCase() ?? '').slice(0, 2).join('')
  }
  return getInitials(email)
}
