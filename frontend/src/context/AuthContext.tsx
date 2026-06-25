"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { authMe, type AuthSession } from "@/lib/api";
import { clearAuth, getAccessToken, SAAS_ENABLED } from "@/lib/auth";

interface AuthContextValue {
  saasEnabled: boolean;
  session: AuthSession | null;
  loading: boolean;
  refresh: () => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue>({
  saasEnabled: SAAS_ENABLED,
  session: null,
  loading: true,
  refresh: async () => {},
  logout: () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(SAAS_ENABLED);

  const refresh = useCallback(async () => {
    if (!SAAS_ENABLED || !getAccessToken()) {
      setSession(null);
      setLoading(false);
      return;
    }
    try {
      setSession(await authMe());
    } catch {
      clearAuth();
      setSession(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const logout = () => {
    clearAuth();
    setSession(null);
    window.location.href = "/login";
  };

  return (
    <AuthContext.Provider value={{ saasEnabled: SAAS_ENABLED, session, loading, refresh, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
