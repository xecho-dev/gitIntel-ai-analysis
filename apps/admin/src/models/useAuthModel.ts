/**
 * Admin Authentication Model (Umi.js model)
 * Manages admin login state using localStorage.
 * Token and user info persist across page refreshes.
 */
import { useState, useEffect, useCallback } from 'react';

export interface AdminUser {
  id: string;
  username: string;
  nickname: string;
  avatar?: string | null;
  role: string;
}

export interface AuthState {
  token: string | null;
  user: AdminUser | null;
  isLoading: boolean;
  isAuthenticated: boolean;
}

const TOKEN_KEY = 'admin_token';
const USER_KEY = 'admin_user';

export function useAuthModel() {
  const [state, setState] = useState<AuthState>({
    token: null,
    user: null,
    isLoading: true,
    isAuthenticated: false,
  });

  // Restore from localStorage on mount
  useEffect(() => {
    try {
      const token = localStorage.getItem(TOKEN_KEY);
      const userStr = localStorage.getItem(USER_KEY);
      const user = userStr ? (JSON.parse(userStr) as AdminUser) : null;
      setState({
        token,
        user,
        isLoading: false,
        isAuthenticated: !!token && !!user,
      });
    } catch {
      setState({ token: null, user: null, isLoading: false, isAuthenticated: false });
    }
  }, []);

  const login = useCallback((token: string, user: AdminUser, expiresAt?: string) => {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem(USER_KEY, JSON.stringify(user));
    if (expiresAt) {
      localStorage.setItem('admin_token_expires_at', expiresAt);
    }
    setState({ token, user, isLoading: false, isAuthenticated: true });
  }, []);

  const logout = useCallback(() => {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    localStorage.removeItem('admin_token_expires_at');
    setState({ token: null, user: null, isLoading: false, isAuthenticated: false });
  }, []);

  return { ...state, login, logout };
}
