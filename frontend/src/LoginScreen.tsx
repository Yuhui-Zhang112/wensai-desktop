import { useState } from 'react';
import { LogIn, UserPlus } from 'lucide-react';
import { login, register } from './services/auth';

const box = { minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24 } as const;
const card = { width: 380, padding: 28, borderRadius: 16, border: '1px solid rgba(0,0,0,.12)', background: 'rgba(255,255,255,.75)', boxShadow: '0 12px 40px rgba(0,0,0,.08)' } as const;
const input = { width: '100%', marginTop: 6, marginBottom: 14, padding: '9px 11px', borderRadius: 8, border: '1px solid rgba(0,0,0,.18)', background: 'transparent', fontFamily: 'inherit', fontSize: 14, color: 'inherit' } as const;

export function LoginScreen({ onSuccess }: { onSuccess: () => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [inviteCode, setInviteCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      if (mode === 'login') await login(username.trim(), password);
      else await register(username.trim(), password, inviteCode.trim());
      onSuccess();
    } catch (problem) {
      setError(problem instanceof Error ? problem.message : '操作失败。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={box}>
      <div style={card}>
        <h1 style={{ fontSize: 20, margin: '0 0 4px' }}>问赛 · 文档评审</h1>
        <p style={{ color: '#666', fontSize: 13, margin: '0 0 20px' }}>
          {mode === 'login' ? '登录后只能看到自己的项目与材料。' : '注册需要邀请码，请联系管理员获取。'}
        </p>

        <label style={{ fontSize: 13 }}>用户名
          <input style={input} value={username} autoComplete="username"
                 onChange={event => setUsername(event.target.value)} />
        </label>
        <label style={{ fontSize: 13 }}>密码
          <input style={input} type="password" value={password} autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                 onChange={event => setPassword(event.target.value)} />
        </label>
        {mode === 'register' && (
          <label style={{ fontSize: 13 }}>邀请码
            <input style={input} value={inviteCode} placeholder="WS-XXXXXXXX"
                   onChange={event => setInviteCode(event.target.value)} />
          </label>
        )}

        {error && <p role="alert" style={{ color: '#b42318', fontSize: 13, margin: '0 0 12px' }}>{error}</p>}

        <button className="button" style={{ width: '100%' }} disabled={busy || !username.trim() || password.length < 8}
                onClick={submit}>
          {mode === 'login' ? <><LogIn size={16} /> 登录</> : <><UserPlus size={16} /> 注册并登录</>}
        </button>

        <p style={{ fontSize: 13, margin: '16px 0 0', textAlign: 'center' }}>
          {mode === 'login' ? '有邀请码？' : '已有账号？'}
          <button className="button" style={{ marginLeft: 6, padding: '2px 8px' }}
                  onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError(''); }}>
            {mode === 'login' ? '注册' : '去登录'}
          </button>
        </p>
      </div>
    </div>
  );
}
