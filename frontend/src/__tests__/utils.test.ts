import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { formatDate, getInitials, profileInitials } from '../utils'

// ── formatDate ────────────────────────────────────────────────────────────────

describe('formatDate', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2025-06-15T12:00:00Z'))
  })
  afterEach(() => vi.useRealTimers())

  it('returns "Just now" for timestamps under a minute ago', () => {
    const ts = new Date(Date.now() - 30_000).toISOString()
    expect(formatDate(ts)).toBe('Just now')
  })

  it('returns minutes for timestamps under an hour ago', () => {
    const ts = new Date(Date.now() - 5 * 60_000).toISOString()
    expect(formatDate(ts)).toBe('5m ago')
  })

  it('returns hours for timestamps under a day ago', () => {
    const ts = new Date(Date.now() - 3 * 3_600_000).toISOString()
    expect(formatDate(ts)).toBe('3h ago')
  })

  it('returns days for timestamps under a week ago', () => {
    const ts = new Date(Date.now() - 4 * 86_400_000).toISOString()
    expect(formatDate(ts)).toBe('4d ago')
  })

  it('returns a formatted date for timestamps older than a week', () => {
    const ts = new Date(Date.now() - 10 * 86_400_000).toISOString()
    // just verify it looks like "Jun 5" style (locale-dependent but deterministic)
    expect(formatDate(ts)).toMatch(/[A-Z][a-z]+ \d+/)
  })
})

// ── getInitials ───────────────────────────────────────────────────────────────

describe('getInitials', () => {
  it('extracts initials from a simple email', () => {
    expect(getInitials('john@example.com')).toBe('J')
  })

  it('extracts two initials from dot-separated local parts', () => {
    expect(getInitials('john.doe@example.com')).toBe('JD')
  })

  it('handles underscore separators', () => {
    expect(getInitials('john_doe@example.com')).toBe('JD')
  })

  it('handles dash separators', () => {
    expect(getInitials('john-doe@example.com')).toBe('JD')
  })

  it('only uses up to two parts', () => {
    expect(getInitials('a.b.c@example.com')).toBe('AB')
  })

  it('uppercases the result', () => {
    expect(getInitials('alice@example.com')).toBe('A')
  })
})

// ── profileInitials ───────────────────────────────────────────────────────────

describe('profileInitials', () => {
  it('uses display name when set', () => {
    expect(profileInitials('John Doe', 'j@x.com')).toBe('JD')
  })

  it('falls back to email initials when display name is empty', () => {
    expect(profileInitials('', 'alice.bob@x.com')).toBe('AB')
  })

  it('falls back when display name is only whitespace', () => {
    expect(profileInitials('   ', 'alice@x.com')).toBe('A')
  })

  it('handles single-word display name', () => {
    expect(profileInitials('Alice', 'a@x.com')).toBe('A')
  })

  it('caps at two initials from display name', () => {
    expect(profileInitials('Jean Claude Van Damme', 'j@x.com')).toBe('JC')
  })

  it('uppercases display name initials', () => {
    expect(profileInitials('john doe', 'j@x.com')).toBe('JD')
  })
})
