import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { LoginScreen } from './LoginScreen';
import { authEnabled, currentUser, getToken } from './services/auth';

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'out' | 'in'>('checking');

  useEffect(() => {
    if (!authEnabled()) { setState('in'); return; }
    if (!getToken()) { setState('out'); return; }
    let alive = true;
    currentUser().then(user => { if (alive) setState(user ? 'in' : 'out'); });
    return () => { alive = false; };
  }, []);

  if (!authEnabled()) return <>{children}</>;
  if (state === 'checking') {
    return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>正在检查登录状态…</div>;
  }
  if (state === 'out') return <LoginScreen onSuccess={() => setState('in')} />;
  return <>{children}</>;
}
