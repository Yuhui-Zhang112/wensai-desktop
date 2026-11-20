import { useEffect, useState } from 'react';
import type { Profile } from './domain';
import { HttpService, approvals } from './services/http';
import type { ScopePreview } from './services/http';
const api = new HttpService();
export function ScopeApproval({ materialId, profile, goal = '', parentTaskId, onReady }: { materialId: string; profile: Profile; goal?: string; parentTaskId?: string; onReady: (ready: boolean) => void }) {
  const [provider, setProvider] = useState<'mock' | 'deepseek'>('mock');
  const [scope, setScope] = useState<ScopePreview | null>(null);
  const [error, setError] = useState('');
  const [retry, setRetry] = useState(0);
  const [selection, setSelection] = useState<string[] | undefined>();
  const [approved, setApproved] = useState(false);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    let current = true;
    setScope(null); setError(''); setApproved(false); onReady(false); setDirty(false);
    const key = `${materialId}:${profile}`;
    approvals.delete(key);
    api.request<ScopePreview>('/scope', { method: 'POST', body: JSON.stringify({ materialId, profile, provider, blockIds: selection, executionMode: goal.trim() ? 'agent' : 'pipeline', goal, parentTaskId }) })
      .then(value => { if (current) setScope(value); }).catch(e => { if (current) setError(e.message); });
    return () => { current = false; approvals.delete(key); };
  }, [materialId, profile, provider, goal, parentTaskId, retry]);
  return <div className="scope-approval"><label className="field">评审方式<select value={provider} onChange={e => { setProvider(e.target.value as 'mock' | 'deepseek'); setSelection(undefined); }}><option value="mock">离线 C Mock · 不联网，固定教学样例</option><option value="deepseek">DeepSeek · 真实外部模型（需要本机凭据）</option></select></label>
    {error ? <p role="alert" className="error-text">{error}<button type="button" className="button" onClick={() => setRetry(n => n + 1)}>重试预览</button></p> : !scope ? <p className="subtle">正在解析并准备准确选段…</p> : <>
      <p className="small">发送目标：{scope.destination}</p>{scope.goal && <p className="small">本轮任务：{scope.goal}</p>}{scope.context && <details><summary>本次将携带的上一轮公开摘要（完整）</summary><pre className="agent-context">{scope.context}</pre></details>}<p className="small subtle">{scope.note} 可取消不需要的文字块，再点击“更新评审范围”。</p>
      <div className="scope-text">{scope.text.map(span => <label key={span.block_id} className="scope-block"><input type="checkbox" defaultChecked onChange={e => { setDirty(true); setApproved(false); onReady(false); approvals.delete(`${materialId}:${profile}`); const current = selection || scope.text.map(s => s.block_id); setSelection(e.target.checked ? [...new Set([...current, span.block_id])] : current.filter(id => id !== span.block_id)); }}/><span><small>{span.block_id}</small><p>{span.text}</p></span></label>)}</div>
      <button type="button" className="button" onClick={() => setRetry(n => n + 1)}>更新评审范围</button>
      <label className="check-row"><input type="checkbox" disabled={dirty} checked={approved} onChange={e => { setApproved(e.target.checked); if (e.target.checked) approvals.set(`${materialId}:${profile}`, scope); else approvals.delete(`${materialId}:${profile}`); onReady(e.target.checked); }}/>{dirty ? '范围已变化，请先更新预览。' : provider === 'deepseek' ? '我已核对上方完整选段，同意仅将这些文字发送至所列 DeepSeek 服务。' : '我已核对范围，确认执行离线 Mock（不代表真实模型评审）。'}</label>
      <p className="micro">版本 {scope.versionId} · 摘要 {scope.textDigest.slice(0, 16)}…</p>
    </>}
  </div>;
}
