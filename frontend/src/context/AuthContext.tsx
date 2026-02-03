import { createContext, useContext, useEffect, useState, ReactNode } from 'react'
import { auth } from '../services/api'
import type { User } from '../types'

interface AuthContextType {
  user: User | null
  isAuthenticated: boolean
  isLoading: boolean
  login: () => void
  logout: () => Promise<void>
  setToken: (token: string) => void
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [isLoading, setIsLoading] = useState(true)

  useEffect(() => {
    const token = localStorage.getItem('token')
    if (token) {
      auth.me()
        .then(setUser)
        .catch(() => {
          localStorage.removeItem('token')
        })
        .finally(() => setIsLoading(false))
    } else {
      setIsLoading(false)
    }
  }, [])

  const login = () => {
    window.location.href = auth.getLoginUrl()
  }

  const logout = async () => {
    try {
      await auth.logout()
    } catch {
      // Ignore errors
    }
    localStorage.removeItem('token')
    setUser(null)
    window.location.href = '/'
  }

  const setToken = (token: string) => {
    localStorage.setItem('token', token)
    auth.me()
      .then(setUser)
      .catch(() => {
        localStorage.removeItem('token')
      })
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        logout,
        setToken,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const context = useContext(AuthContext)
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}
