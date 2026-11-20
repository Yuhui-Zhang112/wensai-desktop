import { useEffect, useState } from 'react';
import { KeyRound } from 'lucide-react';
import { config } from './config';
import { clearCredential, credentialStatus, saveCredential } from './services/credentials';

export function CredentialPanel() {
  const [configured, setConfigured] = useState<boolean | null>(null);
  const [draft, setDraft] = useState('');
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (config.mode !== 'real') return;
    credentialStatus()
      .then(status => setConfigured(status.configured))
      .catch(error => setMessage(error instanceof Error ? error.message : '读取凭据状态失败。'));
  }, []);

  if (config.mode !== 'real') {
    return (
      <div className="settings-panel">
        <h3><KeyRound size={18} />DeepSeek 凭据</h3>
        <p className="subtle">当前是演示模式，不连接本地服务，无法保存凭据。切到真实模式后再配置。</p>
      </div>
    );
  }

  const save = async () => {
    setBusy(true);
    setMessage('');
    try {
      const status = await saveCredential(draft.trim());
      setConfigured(status.configured);
      setDraft('');
      setMessage('已保存到系统钥匙串，下一次评审立即生效。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '保存失败。');
    } finally {
      setBusy(false);
    }
  };

  const clear = async () => {
    setBusy(true);
    setMessage('');
    try {
      const status = await clearCredential();
      setConfigured(status.configured);
      setMessage('已从系统钥匙串移除。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '清除失败。');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="settings-panel">
      <h3><KeyRound size={18} />DeepSeek 凭据</h3>
      <p>保存到系统密钥管理器，不写入数据库、日志或浏览器存储；保存后立即生效，无需重启。</p>
      <div className="setting-line">
        <span>当前状态</span>
        <code>{configured === null ? '读取中…' : configured ? '已配置' : '未配置（仅 Mock 演示）'}</code>
      </div>
      <div className="setting-line" style={{ alignItems: 'center' }}>
        <span>API Key</span>
        <input
          type="password"
          value={draft}
          autoComplete="off"
          spellCheck={false}
          placeholder="sk-..."
          onChange={event => setDraft(event.target.value)}
          style={{ flex: 1, minWidth: 240, padding: '8px 10px', borderRadius: 8, border: '1px solid rgba(0,0,0,.18)', background: 'transparent', color: 'inherit', fontFamily: 'inherit' }}
        />
      </div>
      <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
        <button className="button" onClick={save} disabled={busy || draft.trim().length < 8}>保存</button>
        <button className="button" onClick={clear} disabled={busy || !configured}>清除</button>
      </div>
      {message && <p className="subtle" role="status">{message}</p>}
    </div>
  );
}
