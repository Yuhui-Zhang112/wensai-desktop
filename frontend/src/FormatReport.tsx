import { useState } from 'react';
import type { Material, Profile } from './domain';
import { HttpService } from './services/http';
const api = new HttpService();
interface Report { versionId: string; report: { summary: Record<string, number>; findings: { rule_id: string; status: string; message: string; source: { path: string } | null }[] } }
export function FormatReport({ material }: { material: Material }) {
  const [profile,setProfile]=useState<Profile>(material.kind==='pptx'?'slides':'paper');
  const [report,setReport]=useState<Report|null>(null);const [error,setError]=useState('');const [busy,setBusy]=useState(false);
  const labels:Record<string,string>={pass:'通过',fail:'需修改',needs_review:'需人工复核',not_applicable:'不适用'};
  return <div className="version-actions"><h3>B 确定性格式检查</h3><p className="micro">本机运行，不调用模型。不推测 DOCX 页数或未知格式属性。</p><div className="row"><select aria-label="格式检查类型" value={profile} onChange={e=>{setProfile(e.target.value as Profile);setReport(null);}}><option value="paper">论文</option><option value="proposal">计划书</option><option value="slides">PPT</option></select><button className="button compact" disabled={busy} onClick={async()=>{setBusy(true);setError('');try{setReport(await api.request(`/materials/${encodeURIComponent(material.id)}/format?profile=${profile}`));}catch(e){setError(e instanceof Error?e.message:'检查失败');}finally{setBusy(false);}}}>检查格式</button></div>{error&&<p className="error-text">{error}</p>}{report&&<><p className="small subtle">{Object.entries(report.report.summary).map(([key,count])=>`${labels[key]} ${count}`).join(' · ')}</p><details><summary>查看检查结果</summary>{report.report.findings.map((f,index)=><div className="format-finding" key={index}><strong>{labels[f.status]||f.status} · {f.rule_id}</strong><p>{f.message}</p>{f.source&&<button className="text-button" onClick={()=>document.getElementById('block-'+f.source!.path)?.scrollIntoView({block:'center',behavior:'smooth'})}>{f.source.path}</button>}</div>)}</details></>}</div>;
}
