'use client'

import { useState, useEffect } from 'react'
import { useAuth } from './AuthProvider'
import { useRouter } from 'next/navigation'

export default function Login() {
  const [mode, setMode] = useState<'magic' | 'password'>('magic')
  const [isSignUp, setIsSignUp] = useState(false)
  const [showForgotPassword, setShowForgotPassword] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  const { signIn, signInWithOtp, signUp, resetPassword } = useAuth()
  const router = useRouter()

  useEffect(() => {
    if (typeof window !== 'undefined') {
      const params = new URLSearchParams(window.location.search)
      const errorParam = params.get('error')
      if (errorParam) {
        setError(decodeURIComponent(errorParam))
        window.history.replaceState({}, '', '/login')
      }
    }
  }, [])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError('')
    setMessage('')

    const timeoutId = setTimeout(() => {
      setError('Request is taking too long. Check your network connection.')
      setLoading(false)
    }, 20000)

    try {
      if (mode === 'magic') {
        const { error } = await signInWithOtp(email)
        if (error) throw error
        clearTimeout(timeoutId)
        setMessage('Check your email for a login link. Click it to sign in.')
      } else if (showForgotPassword) {
        if (!email) { setError('Please enter your email address'); setLoading(false); return }
        const { error } = await resetPassword(email)
        if (error) throw error
        clearTimeout(timeoutId)
        setMessage('Check your email for a password reset link.')
        setShowForgotPassword(false)
      } else if (isSignUp) {
        const result = await signUp(email, password)
        if (result.error) throw result.error
        clearTimeout(timeoutId)
        if (result.data?.session) {
          setMessage('Account created! Redirecting...')
        } else {
          setMessage('Check your email to confirm your account.')
        }
      } else {
        const { error } = await signIn(email, password)
        if (error) throw error
        clearTimeout(timeoutId)
      }
    } catch (err: any) {
      clearTimeout(timeoutId)
      const msg = err?.message || 'Authentication failed'
      setError(
        msg.toLowerCase().includes('invalid') || msg.toLowerCase().includes('credentials')
          ? 'Invalid email or password. Please try again.'
          : msg
      )
    } finally {
      clearTimeout(timeoutId)
      setLoading(false)
    }
  }

  return (
    <div
      className="min-h-screen flex items-center justify-center p-6"
      style={{ background: 'var(--bg)' }}
    >
      <div
        className="w-full max-w-md rounded-xl p-8 space-y-6"
        style={{ background: 'var(--s1)', border: '1px solid rgba(20,184,166,0.2)' }}
      >
        {/* Logo */}
        <div className="text-center space-y-1">
          <div className="text-2xl font-bold tracking-widest" style={{ color: 'var(--t0)', fontFamily: 'IBM Plex Mono, monospace' }}>
            PARITY
          </div>
          <div className="text-xs tracking-widest uppercase" style={{ color: 'var(--accent)', fontFamily: 'IBM Plex Sans, sans-serif' }}>
            Intelligence Infrastructure
          </div>
        </div>

        {/* Mode toggle */}
        <div className="flex rounded-lg overflow-hidden" style={{ border: '1px solid rgba(20,184,166,0.25)' }}>
          <button
            type="button"
            onClick={() => { setMode('magic'); setError(''); setMessage('') }}
            className="flex-1 py-2 text-sm font-medium transition-colors"
            style={{
              background: mode === 'magic' ? 'var(--accent)' : 'transparent',
              color: mode === 'magic' ? '#fff' : 'var(--t1)',
            }}
          >
            Magic Link
          </button>
          <button
            type="button"
            onClick={() => { setMode('password'); setError(''); setMessage('') }}
            className="flex-1 py-2 text-sm font-medium transition-colors"
            style={{
              background: mode === 'password' ? 'var(--accent)' : 'transparent',
              color: mode === 'password' ? '#fff' : 'var(--t1)',
            }}
          >
            Password
          </button>
        </div>

        {/* Error / success */}
        {error && (
          <div className="p-3 rounded-lg text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.4)', color: 'var(--red)' }}>
            {error}
          </div>
        )}
        {message && (
          <div className="p-3 rounded-lg text-sm" style={{ background: 'rgba(20,184,166,0.1)', border: '1px solid rgba(20,184,166,0.4)', color: 'var(--accent)' }}>
            {message}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium mb-1.5" style={{ color: 'var(--t1)' }}>
              Email address
            </label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
              placeholder="you@example.com"
              className="w-full px-3 py-2.5 rounded-lg text-sm outline-none transition-colors"
              style={{
                background: 'var(--s2)',
                border: '1px solid rgba(20,184,166,0.25)',
                color: 'var(--t0)',
              }}
            />
          </div>

          {mode === 'password' && !showForgotPassword && (
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-medium" style={{ color: 'var(--t1)' }}>Password</label>
                {!isSignUp && (
                  <button type="button" onClick={() => { setShowForgotPassword(true); setError(''); setMessage('') }}
                    className="text-xs" style={{ color: 'var(--accent)' }}>
                    Forgot password?
                  </button>
                )}
              </div>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                minLength={6}
                placeholder="••••••••"
                className="w-full px-3 py-2.5 rounded-lg text-sm outline-none"
                style={{ background: 'var(--s2)', border: '1px solid rgba(20,184,166,0.25)', color: 'var(--t0)' }}
              />
            </div>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2.5 rounded-lg font-semibold text-sm transition-opacity"
            style={{ background: 'var(--accent)', color: '#fff', opacity: loading ? 0.7 : 1 }}
          >
            {loading ? (
              <span className="flex items-center justify-center gap-2">
                <svg className="animate-spin h-4 w-4" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
                {mode === 'magic' ? 'Sending link...' : showForgotPassword ? 'Sending...' : isSignUp ? 'Creating account...' : 'Signing in...'}
              </span>
            ) : (
              mode === 'magic' ? 'Send Login Link' : showForgotPassword ? 'Send Reset Link' : isSignUp ? 'Create Account' : 'Sign In'
            )}
          </button>
        </form>

        {mode === 'password' && (
          <div className="text-center">
            {showForgotPassword ? (
              <button type="button" onClick={() => { setShowForgotPassword(false); setError(''); setMessage('') }}
                className="text-xs" style={{ color: 'var(--t2)' }}>
                Back to sign in
              </button>
            ) : (
              <button type="button" onClick={() => { setIsSignUp(!isSignUp); setError(''); setMessage('') }}
                className="text-xs" style={{ color: 'var(--t2)' }}>
                {isSignUp ? 'Already have an account? Sign in' : "Don't have an account? Sign up"}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
