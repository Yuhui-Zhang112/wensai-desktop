import { config } from '../config';

const KEY = 'wensai.token';

export interface SessionUser { id: string; username: string }

export function getToken(): string | null {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

export function setToken(token: string | null): void {
  try { token ? localStorage.setItem(KEY, token) : localStorage.removeItem(KEY); } catch { /* 隐私模式下忽略 */ }
}

export const authEnabled = () => config.mode === 'real';

async function post<T>(path: string, body: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${config.apiBase}/api/v1/auth${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(20000),
    });
  } catch {
    throw new Error('无法连接服务，请确认服务已启动或网络正常。');
  }
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error?.message || `操作失败（${response.status}）。`);
  }
  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<SessionUser> {
  const result = await post<{ token: string; user: SessionUser }>('/login', { username, password });
  setToken(result.token);
  return result.user;
}

export async function register(username: string, password: string, inviteCode: string): Promise<SessionUser> {
  const result = await post<{ token: string; user: SessionUser }>('/register', { username, password, inviteCode });
  setToken(result.token);
  return result.user;
}

export async function currentUser(): Promise<SessionUser | null> {
  const token = getToken();
  if (!token) return null;
  try {
    const response = await fetch(`${config.apiBase}/api/v1/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) { setToken(null); return null; }
    const data = await response.json() as { user: SessionUser };
    return data.user;
  } catch {
    return null;
  }
}

export async function logout(): Promise<void> {
  const token = getToken();
  setToken(null);
  if (!token) return;
  try {
    await fetch(`${config.apiBase}/api/v1/auth/logout`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } });
  } catch { /* 本地已清，忽略 */ }
}
