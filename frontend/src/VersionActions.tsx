import { useRef, useState } from 'react';
import { config } from './config';
import type { Material } from './domain';
import { chooseSaveTarget, writeTarget } from './platform';
import { HttpService } from './services/http';
const api = new HttpService();
export function VersionActions({ material, onSaved }: { material: Material; onSaved: (value: Material) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  async function download(id: string, name: string) {
    setBusy(true); setError('');
    try {
      const target = await chooseSaveTarget(name, material.name); if (!target) return;
      const response = await fetch(`${config.apiBase}/api/v1/desktop/versions/${encodeURIComponent(id)}/download`);
      if (!response.ok) throw new Error('下载失败，请检查本地服务及原始文件是否可读。');
      await writeTarget(target, new Uint8Array(await response.arrayBuffer()));
    } catch (e) { setError(e instanceof Error ? e.message : '下载失败。'); }
    finally { setBusy(false); }
  }
  return <div className="version-actions"><div className="row"><button type="button" className="button compact" disabled={busy || !material.originalVersionId} onClick={() => void download(material.originalVersionId!, '原始副本-' + material.name)}>下载原始版本</button><button type="button" className="button compact" disabled={busy || !material.versionId} onClick={() => void download(material.versionId!, '最新副本-' + material.name)}>下载最新版本</button></div>
    {material.kind !== 'pdf' && <button type="button" className="button compact" disabled={busy} onClick={() => input.current?.click()}>上传修改后的同格式新版本</button>}
    <input className="hidden" ref={input} type="file" accept={`.${material.kind}`} onChange={async e => {
      const file = e.target.files?.[0]; e.target.value = ''; if (!file) return;
      setBusy(true); setError('');
      try {
        const body = new FormData(); body.append('file', file); body.append('source_version_id', material.versionId || '');
        const response = await fetch(`${config.apiBase}/api/v1/materials/${encodeURIComponent(material.id)}/versions`, { method: 'POST', body });
        if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.error?.message || '保存新版本失败。'); }
        const list = await api.listMaterials(material.projectId); const value = list.find(m => m.id === material.id); if (value) onSaved(value);
      } catch (e) { setError(e instanceof Error ? e.message : '保存失败。'); }
      finally { setBusy(false); }
    }}/>{error && <p role="alert" className="error-text">{error}</p>}<p className="micro">同格式版本上传保留完整文件；不会把 AI 的修改意见直接写成正文。</p></div>;
}
