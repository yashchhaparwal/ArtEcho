import React, { createContext, useContext, useState, useEffect } from 'react';
import { api } from '../services/api';
import type { UserProfile } from '../services/api';

interface AuthContextType {
  user: UserProfile | null;
  token: string | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, name?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [token, setToken] = useState<string | null>(() => localStorage.getItem('muse_access_token'));
  const [loading, setLoading] = useState<boolean>(true);

  const fetchCurrentUser = async () => {
    try {
      const response = await api.get<UserProfile>('/auth/me');
      setUser(response.data);
    } catch (err) {
      console.error('Failed to fetch current user profile:', err);
      logout();
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (token) {
      fetchCurrentUser();
    } else {
      setLoading(false);
    }
  }, [token]);

  const login = async (email: string, password: string) => {
    const response = await api.post<{ access_token: string }>('/auth/login/json', { email, password });
    const newToken = response.data.access_token;
    localStorage.setItem('muse_access_token', newToken);
    setToken(newToken);
    const userRes = await api.get<UserProfile>('/auth/me', {
      headers: { Authorization: `Bearer ${newToken}` }
    });
    setUser(userRes.data);
  };

  const signup = async (email: string, password: string, name?: string) => {
    await api.post('/auth/signup', { email, password, name });
    await login(email, password);
  };

  const logout = () => {
    localStorage.removeItem('muse_access_token');
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};
