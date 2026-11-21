import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { LoginScreen } from './LoginScreen';
import { authStatus, currentUser, getToken, isRealMode } from './services/auth';

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<'checking' | 'out' | 'in'>('checking');

  useEffect(() => {
    let alive = true;
    (async () => {
      if (!isRealMode()) { if (alive) setState('in'); return; }
      const required = await authStatus();
      if (!alive) return;
      if (!required) { setState('in'); return; }
      if (!getToken()) { setState('out'); return; }
      const user = await currentUser();
      if (alive) setState(user ? 'in' : 'out');
    })();
    return () => { alive = false; };
  }, []);

  if (!isRealMode()) return <>{children}</>;
  if (state === 'checking') {
    return <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>正在检查登录状态…</div>;
  }
  if (state === 'out') return <LoginScreen onSuccess={() => setState('in')} />;
  return <>{children}</>;
}
