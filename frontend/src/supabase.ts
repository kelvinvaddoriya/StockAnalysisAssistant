import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY as string

export const supabase = createClient(supabaseUrl, supabaseAnonKey)

/** Origin of the backend. The SPA and the API are on different hosts in
 *  production (Vercel and Render), so /api/* calls need an absolute URL.
 *  Left unset in dev, where vite.config.ts proxies /api to localhost:8888. */
const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined) ?? ''

/** fetch() that attaches the current Supabase access token as a Bearer header.
 *  Backend endpoints under /api/* require it. */
export async function authedFetch(input: RequestInfo | URL, init: RequestInit = {}): Promise<Response> {
  const { data: { session } } = await supabase.auth.getSession()
  const headers = new Headers(init.headers)
  if (session?.access_token) {
    headers.set('Authorization', `Bearer ${session.access_token}`)
  }
  const url = typeof input === 'string' && input.startsWith('/api') ? `${API_BASE}${input}` : input
  return fetch(url, { ...init, headers })
}
