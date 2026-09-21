import React, { createContext, useContext, useEffect, useState } from 'react';
import { createClient } from '@supabase/supabase-js';
import { SUPABASE_URL, SUPABASE_ANON_KEY } from './config';

const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

const AuthContext = createContext();

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const session = supabase.auth.session?.() || supabase.auth.getSession?.();
    setUser(session?.user || null);
    setLoading(false);
    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user || null);
    });
    return () => {
      listener?.unsubscribe?.();
    };
  }, []);

  const login = async (email, password) => {
    const { user, error } = await supabase.auth.signInWithPassword({ email, password });
    setUser(user || null);
    return { user, error };
  };
  const signup = async (email, password) => {
    const { user, error } = await supabase.auth.signUp({ email, password });
    setUser(user || null);
    return { user, error };
  };
  const logout = async () => {
    await supabase.auth.signOut();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, login, signup, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
} 