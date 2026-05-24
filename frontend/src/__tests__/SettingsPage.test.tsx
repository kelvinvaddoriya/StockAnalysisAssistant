import { describe, it, expect, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import '@testing-library/jest-dom'
import SettingsPage from '../SettingsPage'

// Mock Supabase so no real network calls happen
vi.mock('../supabase', () => ({
  supabase: {
    auth: {
      updateUser: vi.fn().mockResolvedValue({ data: {}, error: null }),
    },
  },
}))

const TEST_USER = { email: 'alice@example.com', id: 'user-123' }

function renderSettings(overrides: Partial<Parameters<typeof SettingsPage>[0]> = {}) {
  const onSave = vi.fn()
  render(
    <SettingsPage
      user={TEST_USER}
      displayName=""
      avatarUrl=""
      onSave={onSave}
      {...overrides}
    />
  )
  return { onSave }
}

// ── initial render ────────────────────────────────────────────────────────────

describe('SettingsPage — initial render', () => {
  it('shows the section labels', () => {
    renderSettings()
    expect(screen.getByText('Profile')).toBeInTheDocument()
    expect(screen.getByText('How to use Bourse')).toBeInTheDocument()
  })

  it('renders the email as read-only', () => {
    renderSettings()
    const emailInput = screen.getByDisplayValue(TEST_USER.email)
    expect(emailInput).toHaveAttribute('readonly')
  })

  it('pre-fills the display name field', () => {
    renderSettings({ displayName: 'Alice' })
    expect(screen.getByDisplayValue('Alice')).toBeInTheDocument()
  })

  it('shows "Save changes" button', () => {
    renderSettings()
    expect(screen.getByRole('button', { name: /save changes/i })).toBeInTheDocument()
  })

  it('shows all four usage guide steps', () => {
    renderSettings()
    expect(screen.getByText('01')).toBeInTheDocument()
    expect(screen.getByText('02')).toBeInTheDocument()
    expect(screen.getByText('03')).toBeInTheDocument()
    expect(screen.getByText('04')).toBeInTheDocument()
  })
})

// ── display name editing ──────────────────────────────────────────────────────

describe('SettingsPage — display name', () => {
  it('updates the input as the user types', async () => {
    const user = userEvent.setup()
    renderSettings()
    const input = screen.getByPlaceholderText('Your name')
    await user.clear(input)
    await user.type(input, 'Bob')
    expect(screen.getByDisplayValue('Bob')).toBeInTheDocument()
  })

  it('calls onSave with the new display name on save', async () => {
    const user = userEvent.setup()
    const { onSave } = renderSettings()
    const input = screen.getByPlaceholderText('Your name')
    await user.clear(input)
    await user.type(input, 'Bob Smith')
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Bob Smith', ''))
  })

  it('trims leading/trailing whitespace on save', async () => {
    const user = userEvent.setup()
    const { onSave } = renderSettings()
    const input = screen.getByPlaceholderText('Your name')
    await user.clear(input)
    await user.type(input, '  Carol  ')
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('Carol', ''))
  })
})

// ── save feedback ─────────────────────────────────────────────────────────────

describe('SettingsPage — save feedback', () => {
  it('shows "✓  Saved" after a successful save', async () => {
    const user = userEvent.setup()
    renderSettings()
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /saved/i })).toBeInTheDocument())
  })

  it('disables the save button while saving', async () => {
    const user = userEvent.setup()
    renderSettings()
    const btn = screen.getByRole('button', { name: /save changes/i })
    await user.click(btn)
    // Button should be disabled right after click (saving state)
    // By the time we check, it may already be "saved" — either is disabled
    expect(btn).toBeDisabled()
  })
})

// ── avatar removal ────────────────────────────────────────────────────────────

describe('SettingsPage — avatar', () => {
  it('shows "Remove photo" button when an avatar is present', () => {
    renderSettings({ avatarUrl: 'data:image/png;base64,abc' })
    expect(screen.getByRole('button', { name: /remove photo/i })).toBeInTheDocument()
  })

  it('does not show "Remove photo" when no avatar', () => {
    renderSettings({ avatarUrl: '' })
    expect(screen.queryByRole('button', { name: /remove photo/i })).not.toBeInTheDocument()
  })

  it('removes avatar and calls onSave with empty string', async () => {
    const user = userEvent.setup()
    const { onSave } = renderSettings({ avatarUrl: 'data:image/png;base64,abc' })
    await user.click(screen.getByRole('button', { name: /remove photo/i }))
    await user.click(screen.getByRole('button', { name: /save changes/i }))
    await waitFor(() => expect(onSave).toHaveBeenCalledWith('', ''))
  })
})
