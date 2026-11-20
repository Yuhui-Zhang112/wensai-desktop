import { useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { ArrowDownToLine, ArrowLeft, ArrowRight, BookOpen, Check, ChevronDown, ChevronRight, CircleHelp, File, FileText, Folder, FolderPlus, Image, LayoutDashboard, LoaderCircle, MoreHorizontal, Pencil, Play, Plus, RefreshCw, Search, Settings, ShieldCheck, SlidersHorizontal, Sparkles, Trash2, Upload, WifiOff, X } from 'lucide-react';
import { config } from './config';
import { AgentConsole } from './AgentConsole';
import { ScopeApproval } from './ScopeApproval';
import { VersionActions } from './VersionActions';
import { FormatReport } from './FormatReport';
import type { ConnectionState, Decision, Issue, Material, Profile, Project, Task } from './domain';
import { decisionLabels, diffTokens, locationLabel, plainText, profiles, statusLabels } from './domain';
import { mock, service } from './services';
import { chooseSaveTarget, isDesktop, pickMaterial, writeTarget } from './platform';

type Modal = { type: 'project'; id?: string; name: string } | { type: 'delete-project'; id: string; name: string } | { type: 'delete-material'; material: Material } | { type: 'review' } | { type: 'edit'; issue: Issue; text: string } | { type: 'text'; text: string } | { type: 'export' } | null;
type View = 'workspace' | 'projects' | 'settings';
function Empty({ title, children }: { title: string; children?: ReactNode }) { return <div className="empty"><FileText size={34}/><h3>{title}</h3><p>{children}</p></div>; }
function Diff({ issue }: { issue: Issue }) {
  if (issue.suggestionKind === 'advice') return <div className="diff"><span className="micro">修改意见（不是可直接替换的正文）</span><p>{issue.suggestion}</p>{issue.editedText && <><span className="micro">用户拟定正文草稿</span><p>{issue.editedText}</p></>}</div>;
  const next = issue.decision === 'edited' ? issue.editedText ?? issue.suggestion : issue.suggestion;
  const diff = diffTokens(issue.original, next);
  return <div className="diff"><div><span className="micro">原文</span><p>{diff.prefix}<del>{diff.removed}</del>{diff.suffix}</p></div><div><span className="micro">修改后</span><p>{diff.prefix}<ins>{diff.added}</ins>{diff.suffix}</p></div></div>;
}
export default function App() {
  const [view, setView] = useState<View>('workspace');
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectId, setProjectId] = useState(config.mode === 'mock' ? 'p1' : '');
  const [materials, setMaterials] = useState<Material[]>([]);
  const [materialId, setMaterialId] = useState(config.mode === 'mock' ? 'm1' : '');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [taskId, setTaskId] = useState(config.mode === 'mock' ? 't1' : '');
  const [loading, setLoading] = useState(true);
  const [materialsLoading, setMaterialsLoading] = useState(false);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [modal, setModal] = useState<Modal>(null);
  const [agentGoal, setAgentGoal] = useState('按竞赛材料要求检查论证与证据，优先给出修改顺序。');
  const [parentTaskId, setParentTaskId] = useState<string | undefined>();
  function openAgent(goal: string, parentId?: string) { setAgentGoal(goal); setParentTaskId(parentId); setPrivacy(false); setProfile(material?.kind === 'pptx' ? 'slides' : 'paper'); setModal({ type: 'review' }); }
  const [profile, setProfile] = useState<Profile>('paper');
  const [tab, setTab] = useState<'agent' | 'review' | 'tasks' | 'versions'>((config.mode === 'real' || config.agentPreview) ? 'agent' : 'review');
  const [query, setQuery] = useState('');
  const [severity, setSeverity] = useState('全部');
  const [decision, setDecision] = useState('全部');
  const [selectedIssue, setSelectedIssue] = useState('');
  const [selectedBlock, setSelectedBlock] = useState('');
  const [connection, setConnection] = useState<ConnectionState>('live');
  const [privacy, setPrivacy] = useState(false);
  const [simulateFailure, setSimulateFailure] = useState(false);
  const [simulateDisconnect, setSimulateDisconnect] = useState(false);
  const [format, setFormat] = useState<'report' | 'text'>('report');
  const fileInput = useRef<HTMLInputElement>(null);
  const dialogRef = useRef<HTMLDialogElement>(null);
  const project = projects.find(p => p.id === projectId);
  const material = materials.find(m => m.id === materialId);
  const task = tasks.find(t => t.id === taskId) || tasks[0] || null;
  const issues = task?.issues || [];
  const reviewed = issues.filter(i => i.decision !== 'pending').length;
  const retry = () => { setError(''); setRefresh(x => x + 1); };

  useEffect(() => {
    let current = true; setLoading(true);
    service.listProjects().then(list => { if (!current) return; setProjects(list); setProjectId(id => list.some(p => p.id === id) ? id : list[0]?.id || ''); }).catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setLoading(false); });
    return () => { current = false; };
  }, [refresh]);
  useEffect(() => {
    let current = true; setMaterials([]); setTasks([]);
    if (!projectId) return;
    setMaterialsLoading(true);
    service.listMaterials(projectId).then(list => { if (!current) return; setMaterials(list); setMaterialId(id => list.some(m => m.id === id) ? id : list[0]?.id || ''); }).catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setMaterialsLoading(false); });
    return () => { current = false; };
  }, [projectId, refresh]);
  useEffect(() => {
    let current = true; setTasks([]); setSelectedIssue(''); setSelectedBlock(''); setDecision('全部'); setSeverity('全部');
    if (!materialId) return;
    setTasksLoading(true);
    service.listTasks(materialId).then(list => { if (!current) return; setTasks(list); setTaskId(id => list.some(t => t.id === id) ? id : list[0]?.id || ''); }).catch(e => { if (current) setError(e.message); }).finally(() => { if (current) setTasksLoading(false); });
    return () => { current = false; };
  }, [materialId, refresh]);
  const activeTaskId = task && ['queued', 'running', 'cancelling'].includes(task.status) ? task.id : '';
  useEffect(() => {
    if (!activeTaskId) return;
    return service.subscribe(activeTaskId, task?.eventId || 0, event => {
      setTasks(list => list.map(t => t.id === event.task.id ? event.task : t));
    }, setConnection);
    // Subscribe once per task. The adapter retains the last event cursor.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTaskId]);
  useEffect(() => { if (!notice) return; const timer = setTimeout(() => setNotice(''), 5500); return () => clearTimeout(timer); }, [notice]);
  useEffect(() => { if (modal && dialogRef.current && !dialogRef.current.open) dialogRef.current.showModal(); }, [modal]);

  async function action(work: () => Promise<void>) {
    if (busy) return; setBusy(true); setError('');
    try { await work(); } catch (error) { setError(error instanceof Error ? error.message : '操作失败，请重试。'); }
    finally { setBusy(false); }
  }
  async function importFile(file: File) {
    const result = await service.upload(projectId, file);
    setMaterials(list => [...list, result]); setMaterialId(result.id); setView('workspace'); setTab(config.mode === 'real' ? 'agent' : 'review');
    setNotice(result.previewState === 'awaiting-parser' ? result.parseError || '材料已保存，但暂时无法解析，请检查文件。' : config.mode === 'real' ? '材料已导入并由 B 完成解析，已保存到本地。' : '材料已导入；演示数据仅在本次打开期间保留。');
  }
  function chooseImport() {
    if (!projectId) { setNotice('请先创建一个项目。'); return; }
    if (isDesktop()) void action(async () => { const file = await pickMaterial(); if (file) await importFile(file); });
    else fileInput.current?.click();
  }
  function locate(issue: Issue) {
    setSelectedIssue(issue.id); setSelectedBlock(issue.location.blockId);
    document.getElementById(`block-${issue.location.blockId}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }
  function decideIssue(issue: Issue, value: Decision, text?: string) {
    if (!task) return;
    void action(async () => {
      const updated = await service.decide(task.id, issue.id, value, text);
      setTasks(list => list.map(t => t.id === updated.id ? updated : t)); setModal(null);
      setNotice(value === 'pending' ? '已恢复为待处理；原始材料未修改。' : `${decisionLabels[value]}。原始材料未修改，采纳记录不自动替换正文；请在文本编辑器修改后保存新版本。`);
    });
  }
  async function submitModal() {
    if (!modal) return;
    if (modal.type === 'project') {
      const name = modal.name.trim(); if (!name || name.length > 80) throw new Error('项目名称请输入 1–80 个字符。');
      if (modal.id) { await service.renameProject(modal.id, name); setProjects(list => list.map(p => p.id === modal.id ? { ...p, name } : p)); }
      else { const p = await service.createProject(name); setProjects(list => [...list, p]); setProjectId(p.id); setView('workspace'); }
    } else if (modal.type === 'delete-project') {
      await service.deleteProject(modal.id); setProjects(list => list.filter(p => p.id !== modal.id));
      if (projectId === modal.id) setProjectId(projects.find(p => p.id !== modal.id)?.id || '');
    } else if (modal.type === 'delete-material') {
      await service.deleteMaterial(modal.material.id); setMaterials(list => list.filter(m => m.id !== modal.material.id));
      if (materialId === modal.material.id) setMaterialId(materials.find(m => m.id !== materialId)?.id || '');
    } else if (modal.type === 'review' && material) {
      if (!privacy) throw new Error('请先确认数据使用说明。');
      let created = await service.createTask(material.id, profile); if (config.mode === 'mock') created = mock.configureAgentTask(created.id, agentGoal, parentTaskId); setTasks(list => [created, ...list]); setTaskId(created.id); setTab((config.mode === 'real' || config.agentPreview) ? 'agent' : 'tasks');
    } else if (modal.type === 'text' && material) {
      // Real saves carry the complete editor text; splitting would normalize blank lines.
      const texts = config.mode === 'real' ? [modal.text] : modal.text.split(/\r?\n\s*\r?\n/);
      const updated = await service.saveRevision(material.id, texts.map((text, index) => ({ id: `edited-${crypto.randomUUID()}`, kind: 'paragraph', text, paragraph: index + 1 })));
      setMaterials(list => list.map(m => m.id === updated.id ? updated : m)); setNotice('已保存新版本，原始文件和旧版本保留。新版本需要重新评审。'); setTab('versions');
    } else if (modal.type === 'export' && material) {
      const stem = material.name.replace(/\.[^.]+$/, '');
      const name = format === 'report' ? `${stem}-评审记录.json` : `${stem}-修改稿.${material.kind}`;
      // Show a native path chooser before requesting or writing any output.
      const target = await chooseSaveTarget(name, material.name); if (!target) return;
      const result = await service.exportFile(material, task, format); await writeTarget(target, result.bytes);
      setNotice(target.kind === 'desktop' ? `已导出到 ${target.path}。原始文件未修改。` : '已导出到刚才选择的位置。原始文件未修改。');
    }
    setModal(null);
  }
  const filtered = issues.filter(i => (severity === '全部' || i.severity === severity) && (decision === '全部' || i.decision === decision) && `${i.title} ${i.evidence} ${i.standard}`.includes(query));
  const blocks = material?.revisions.at(-1)?.blocks || material?.blocks || [];
  const hasNewVersion = !!material?.revisions.length;
  const canModify = material?.kind !== 'pdf' && (config.mode === 'mock' ? !hasNewVersion : !task?.versionId || task.versionId === material?.versionId);

  return <div className="app">
    <aside className="sidebar">
      <a className="brand" href="#" onClick={e => { e.preventDefault(); setView('workspace'); }}><span className="brand-mark"><BookOpen size={22}/></span><span>问赛<span className="brand-en">WENSAI</span></span></a>
      <span className="nav-caption">工作空间</span>
      <button className={`nav-item ${view === 'workspace' ? 'active' : ''}`} onClick={() => setView('workspace')}><LayoutDashboard size={18}/>智能体工作台</button>
      <button className={`nav-item ${view === 'projects' ? 'active' : ''}`} onClick={() => setView('projects')}><Folder size={18}/>所有项目<span className="nav-count">{projects.length}</span></button>
      <div className="sidebar-heading"><span className="nav-caption">我的项目</span><button className="icon-button" title="创建项目" onClick={() => setModal({ type: 'project', name: '' })}><Plus size={16}/></button></div>
      <div className="project-nav">{projects.map(p => <button key={p.id} className={`project-link ${p.id === projectId ? 'selected' : ''}`} onClick={() => { setProjectId(p.id); setView('workspace'); }}><span className="project-dot"/>{p.name}</button>)}{!loading && !projects.length && <p className="subtle small">还没有项目</p>}</div>
      <div className="sidebar-bottom"><div className="local-card"><ShieldCheck size={19}/><div><strong>本地优先</strong><p>文件仅在明确选择后导入</p></div></div><button className={`nav-item ${view === 'settings' ? 'active' : ''}`} onClick={() => setView('settings')}><Settings size={18}/>设置与隐私</button><div className="sidebar-foot"><span className="avatar">D</span><span>问赛 · 智能体开发版<small>v0.3.0 / {isDesktop() ? 'Desktop' : 'Web preview'}</small></span></div></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumb">工作空间<ChevronRight size={14}/><span>{view === 'settings' ? '设置与隐私' : view === 'projects' ? '所有项目' : project?.name || '评审工作台'}</span></div><div className="topbar-right"><span className={`connection-dot ${config.mode === 'mock' ? '' : 'real'}`}/>{config.mode === 'mock' ? '演示模式 · 未连接 A/B/C' : 'A/B/C 本地整合服务'}<span className="divider"/><button className="icon-button" title="查看对接说明" onClick={() => setNotice('对接范围、启动方法及待 A/B/C 确认的字段，请查看工程 README 与 docs/接口对接.md。')}><CircleHelp size={18}/></button></div></header>
      {config.mode === 'mock' && <div className="demo-banner"><Sparkles size={15}/><span>独立演示环境</span>示例材料与评审结论为固定演示数据，导入的真实材料不会生成虚构评审。<span className="demo-session">刷新后重置</span></div>}
      {error && <div className="error-banner" role="alert"><WifiOff size={18}/><span>{error}</span><button onClick={retry}>重新加载</button><button className="icon-button" title="关闭错误提示" onClick={() => setError('')}><X size={16}/></button></div>}
      {notice && <div className="toast" role="status"><Check size={17}/>{notice}<button className="icon-button" title="关闭通知" onClick={() => setNotice('')}><X size={15}/></button></div>}
      {view === 'settings' ? <section className="page settings-page"><div className="eyebrow">PREFERENCES</div><h1>设置与隐私</h1><p className="subtle">明确数据边界，再开始每一次评审。</p><div className="settings-panel"><h3><ShieldCheck size={18}/>数据使用说明</h3><p>选择材料后，只有该文件会被发送到配置的本地服务。演示模式只保留本次会话中的文本和操作，不写数据库、不读取其他目录、不保存 API Key。</p><p>真实模式将目标、完整确认选段、显示的上一轮摘要及工具结果发送至 DeepSeek deepseek-flash，用于最多8次决策、2轮内容评审。本版不发送图片，默认离线策略演示；每轮均须确认范围和任务摘要。</p><label className="check-row"><input type="checkbox" checked={privacy} onChange={e => setPrivacy(e.target.checked)}/>我已了解本地导入与模型调用的数据边界</label></div><div className="settings-panel"><h3>服务与模型</h3><div className="setting-line"><span>数据模式</span><code>{config.mode === 'mock' ? 'Mock / 固定演示数据' : 'Real / 本地服务'}</code></div><div className="setting-line"><span>统一 API 地址</span><code>{config.apiBase}</code></div><div className="setting-line"><span>模型 / API Key</span><span className="subtle">DeepSeek 凭据仅存系统密钥管理器，使用随包配置模型密钥.cmd在本机设置</span></div><div className="setting-line"><span>材料和导出目录</span><span className="subtle">材料由 A 管理；导出时由用户选择路径</span></div></div>{config.mode === 'mock' && <div className="settings-panel"><h3>异常状态验收</h3><label className="check-row"><input type="checkbox" checked={simulateFailure} onChange={e => { setSimulateFailure(e.target.checked); mock.failure = e.target.checked; }}/>模拟请求失败（启用后点“重新加载”观察）</label><label className="check-row"><input type="checkbox" checked={simulateDisconnect} onChange={e => { setSimulateDisconnect(e.target.checked); mock.disconnected = e.target.checked; }}/>模拟任务事件断线（仅进行中的任务）</label><button className="button" onClick={retry}><RefreshCw size={15}/>重新加载</button></div>}</section>
      : view === 'projects' ? <section className="page"><div className="page-heading"><div><div className="eyebrow">YOUR PROJECTS</div><h1>所有项目</h1><p className="subtle">让材料、评审与修改记录各归其位。</p></div><button className="button primary" onClick={() => setModal({ type: 'project', name: '' })}><FolderPlus size={17}/>创建项目</button></div><div className="project-grid">{projects.map(p => <article className="project-card" key={p.id}><Folder size={26}/><h3>{p.name}</h3><p className="subtle small">更新于 {new Date(p.updatedAt).toLocaleDateString('zh-CN', { timeZone: 'Asia/Shanghai' })}</p><div className="row"><button className="button" onClick={() => { setProjectId(p.id); setView('workspace'); }}>打开项目<ArrowRight size={15}/></button><button className="icon-button" title={`重命名 ${p.name}`} onClick={() => setModal({ type: 'project', id: p.id, name: p.name })}><Pencil size={16}/></button><button className="icon-button danger" title={`删除 ${p.name}`} onClick={() => setModal({ type: 'delete-project', id: p.id, name: p.name })}><Trash2 size={16}/></button></div></article>)}</div>{!projects.length && <Empty title="创建第一个项目">项目可以集中管理材料和评审记录。</Empty>}</section>
      : <section className="workspace">
        <div className="page-heading"><div><div className="eyebrow">GOAL-DRIVEN REVIEW AGENT</div><h1>{project?.name || '评审工作台'}</h1><p className="subtle">给出目标，让智能体选工具、核对证据，与你一起完成评审。</p></div><div className="row"><button className="button" disabled={!material || busy} onClick={() => { setFormat('report'); setModal({ type: 'export' }); }}><ArrowDownToLine size={16}/>导出</button><button className="button primary" disabled={!projectId || busy} onClick={chooseImport}><Plus size={17}/>导入材料</button></div></div>
        <input ref={fileInput} className="hidden" type="file" accept=".docx,.pptx,.pdf,.txt,.md" onChange={e => { const file = e.target.files?.[0]; if (file) void action(() => importFile(file)); e.target.value = ''; }}/>
        <div className="work-layout">
          <section className="materials-panel panel"><div className="panel-title"><h2>项目材料 <span>{materials.length}</span></h2><button className="icon-button" title="刷新材料" onClick={retry}><RefreshCw size={15}/></button></div><div className="material-list">{loading || materialsLoading ? <div className="loading"><LoaderCircle className="spin" size={20}/>正在加载</div> : materials.map(m => <div className={`material-item ${m.id === materialId ? 'selected' : ''}`} key={m.id}><button className="material-select" onClick={() => { setMaterialId(m.id); setTaskId(''); setTab(config.mode === 'real' ? 'agent' : 'review'); }}><span className={`file-icon ${m.kind}`}><FileText size={19}/></span><span className="material-info"><strong>{m.name}</strong><small>{m.kind.toUpperCase()}<span>·</span>{m.demo ? '示例材料' : m.previewState === 'ready' ? '已导入' : '等待解析'}</small></span></button><button className="material-menu icon-button" title={`删除材料 ${m.name}`} onClick={() => setModal({ type: 'delete-material', material: m })}><Trash2 size={13}/></button></div>)}</div><button className="import-zone" onClick={chooseImport} disabled={!projectId || busy}><Upload size={20}/><strong>选择本地文件</strong><span>DOCX、PPTX、PDF、TXT、MD</span><span>单文件不超过 30 MB</span></button><div className="material-note"><ShieldCheck size={14}/><span>原始文件始终保留<br/>修改须保存为新版本</span></div></section>
          <section className="editor-panel panel">{material ? <><div className="document-toolbar"><div><span className={`file-icon small-icon ${material.kind}`}><FileText size={15}/></span><strong title={material.name}>{material.name}</strong></div><div className="row"><span className="pill neutral">{material.kind === 'pdf' ? '只读预览' : hasNewVersion ? `编辑版本 ${material.revisions.length}` : '原始版本'}</span>{['txt', 'md'].includes(material.kind) && <button className="icon-button" title="编辑文本并保存新版本" onClick={() => setModal({ type: 'text', text: material.rawText ?? plainText(blocks) })}><Pencil size={16}/></button>}</div></div><div className="preview-meta"><span>{material.demo ? '示例结构化预览' : 'B 解析 · 结构化预览'}<span className="subtle"> · {material.kind === 'pptx' ? '真实文字解析 · 非原版缩略图' : '按原文位置定位'}</span></span><span>{blocks.length} 个内容块</span></div>{task && hasNewVersion && task.versionId !== material.versionId && <div className="inline-warning">当前预览为新版本；右侧为原版本的评审结果。修改操作已禁用，请为新版本重新评审。</div>}<div className="document-scroll" aria-label="材料预览">{material.previewState === 'awaiting-parser' ? <Empty title={config.mode === 'real' ? '材料解析未完成' : '等待解析服务接入'}>{material.parseError || `无法解析 ${material.kind.toUpperCase()}，请检查文件是否有效。原始文件已保留。`}</Empty> : material.kind === 'pptx' ? <div className="slide-grid">{[...new Set(blocks.map(b => b.slide))].map(slide => <div className="slide" key={slide}><span className="micro">SLIDE {slide}</span>{blocks.filter(b => b.slide === slide).map(b => <div id={`block-${b.id}`} key={b.id} className={selectedBlock === b.id ? 'highlight' : ''}>{b.kind === 'heading' ? <h3>{b.text}</h3> : <p>{b.text}</p>}</div>)}</div>)}</div> : <div className="paper">{blocks.map((b, index) => <div key={b.id} id={`block-${b.id}`} className={`document-block ${selectedBlock === b.id ? 'highlight' : ''}`}>
                {b.page && b.page !== blocks[index - 1]?.page && <div className="page-separator">第 {b.page} 页</div>}
                {b.kind === 'heading' ? index === 0 ? <h2 className="doc-title">{b.text}</h2> : <h3>{b.text}</h3> : b.kind === 'table' ? <><span className="table-caption">{b.text}</span><table><tbody>{b.rows?.map((row, ri) => <tr key={ri}>{row.map((cell, ci) => ri === 0 ? <th key={ci}>{cell}</th> : <td key={ci}>{cell}</td>)}</tr>)}</tbody></table></> : b.kind === 'image' ? <div className="image-placeholder">{b.imageUrl?.startsWith(config.apiBase + '/') ? <img src={b.imageUrl} alt={b.text}/> : <><Image size={30}/><span>{b.text}</span></>}</div> : <p><span className="paragraph-number">{b.paragraph?.toString().padStart(2, '0')}</span>{b.text}</p>}
              </div>)}</div>}</div><footer className="document-footer"><span><ShieldCheck size={13}/>原始文件未修改</span><span>{material.demo ? 'DEMO DOCUMENT' : material.kind.toUpperCase()}</span></footer></> : <Empty title={projectId ? '还没有材料' : '先创建一个项目'}>选择文件后即可查看材料。<br/><button className="button" onClick={() => projectId ? chooseImport() : setModal({ type: 'project', name: '' })}>{projectId ? '导入材料' : '创建项目'}</button></Empty>}</section>
          <section className="review-panel panel"><div className="review-heading"><div><span className="review-spark"><Sparkles size={18}/></span><h2>问赛智能体</h2></div><button className="button primary compact" disabled={!material || busy || material.previewState !== 'ready'} onClick={() => { openAgent(agentGoal); }}><Play size={13}/>开始评审</button></div><div className="tabs" role="tablist" aria-label="评审区域"><button role="tab" aria-selected={tab === 'agent'} className={tab === 'agent' ? 'active' : ''} onClick={() => setTab('agent')}>智能体</button><button role="tab" aria-selected={tab === 'review'} className={tab === 'review' ? 'active' : ''} onClick={() => setTab('review')}>评审结果{issues.length > 0 && <span>{issues.length}</span>}</button><button role="tab" aria-selected={tab === 'tasks'} className={tab === 'tasks' ? 'active' : ''} onClick={() => setTab('tasks')}>任务</button><button role="tab" aria-selected={tab === 'versions'} className={tab === 'versions' ? 'active' : ''} onClick={() => setTab('versions')}>版本</button></div>
            {tab === 'agent' ? <AgentConsole task={task} disabled={!material || busy || material.previewState !== 'ready'} onStart={goal => openAgent(goal)} onContinue={(goal, id) => openAgent(goal, id)} onResults={() => setTab('review')} onCancel={() => { if (task) void action(async () => { await service.cancelTask(task.id); const updated = await service.getTask(task.id); setTasks(list => list.map(t => t.id === updated.id ? updated : t)); }); }}/> : tab === 'tasks' ? <div className="review-scroll">{tasksLoading ? <div className="loading">正在加载任务…</div> : !tasks.length ? <Empty title="还没有评审任务">选择材料和评审类型后开始。</Empty> : tasks.map(t => <article className={`task-card ${task?.id === t.id ? 'selected' : ''}`} key={t.id}><div className="row between"><strong>{profiles[t.profile]}</strong><span className={`pill ${t.status}`}>{statusLabels[t.status]}</span></div><p className="micro">任务 {t.id.slice(0, 8)} · 事件 #{t.eventId}</p>{['queued', 'running', 'cancelling'].includes(t.status) && <><div className="progress"><span style={{ width: `${t.progressKnown === false ? 35 : t.progress}%` }}/></div><p className="small subtle">{t.progressKnown === false ? '执行进度由服务状态表示' : `${t.progress}%`} · {t.id === activeTaskId ? ({ live: '事件连接正常', connecting: '正在连接事件流', reconnecting: '连接中断，按最后事件序号重连…', polling: '正在补拉任务状态', error: '连接失败，自动重试中…' }[connection]) : '选择该任务以跟踪进度'}</p></>}{t.status === 'failed' && <p className="error-text">{t.error || '任务执行失败，请重试。'}</p>}<div className="row"><button className="button compact" onClick={() => { setTaskId(t.id); setTab(t.agent?.mode === 'agent' ? 'agent' : 'review'); }}>{t.status === 'completed' ? '查看结果' : '跟踪任务'}</button>{['queued', 'running'].includes(t.status) && <button className="text-button" disabled={busy} onClick={() => void action(async () => { await service.cancelTask(t.id); const updated = await service.getTask(t.id); setTasks(list => list.map(item => item.id === t.id ? updated : item)); })}>取消任务</button>}{['failed', 'cancelled'].includes(t.status) && <button className="text-button" onClick={() => openAgent(t.agent?.goal || agentGoal)}>重新评审</button>}</div></article>)}</div>
            : tab === 'versions' ? <div className="review-scroll">{config.mode === 'real' && material && <><VersionActions material={material} onSaved={value => { setMaterials(list => list.map(m => m.id === value.id ? value : m)); retry(); }}/><FormatReport material={material}/></>}<p className="version-note">原始版本与编辑副本分开保留。采纳只保存意见与草稿；文本请编辑后保存，Office 请修改副本后上传。</p>{material && <article className="version-card"><span className="version-dot"/><strong>原始版本</strong><small>{material.name}</small><p>{new Date(material.createdAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</p></article>}{material?.revisions.map(r => <article className="version-card" key={r.id}><span className="version-dot"/><strong>{r.name}</strong><p>{new Date(r.createdAt).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })}</p><details><summary>查看版本内容</summary><pre>{plainText(r.blocks)}</pre></details></article>)}</div>
            : tasksLoading ? <div className="loading"><LoaderCircle className="spin" size={18}/>读取评审结果…</div> : !task || task.status !== 'completed' ? <Empty title={task ? statusLabels[task.status] : '准备好开始评审了吗'}>{task ? '在任务页查看进度、取消或重试。' : '选择适合材料的评审类型，问题、证据和修改建议将显示在这里。'}</Empty> : <><div className="review-summary">{task.result && <><p className="small subtle">{task.result.review.summary}</p><p className="small">总分：{task.result.total_score == null ? '证据不足，暂不计总分' : `${task.result.total_score} / 100`}</p><details><summary>查看维度评分（0–10）</summary>{task.result.review.dimensions.map(d => <p className="small subtle" key={d.id}>{d.id}：{d.score == null ? '证据不足' : `${d.score} / 10`}</p>)}</details></>}<div><strong>{issues.length}</strong><span>条评审建议</span><span className="summary-separator"/><span>已处理 <b>{reviewed}/{issues.length}</b></span></div><div className="summary-progress"><span style={{ width: `${issues.length ? reviewed / issues.length * 100 : 0}%` }}/></div><span className="micro">{task.materialId === 'm1' && config.mode === 'mock' ? '固定示例 · 非模型生成' : '保留服务返回的严重程度与结论'}</span></div><div className="review-filters"><div className="search"><Search size={14}/><input aria-label="搜索评审结果" placeholder="搜索问题、证据或标准" value={query} onChange={e => setQuery(e.target.value)}/></div><div className="row"><label className="filter"><SlidersHorizontal size={13}/><select aria-label="严重程度筛选" value={severity} onChange={e => setSeverity(e.target.value)}><option>全部</option>{[...new Set(issues.map(i => i.severity))].map(s => <option key={s}>{s}</option>)}</select></label><select className="decision-filter" aria-label="处理状态筛选" value={decision} onChange={e => setDecision(e.target.value)}><option value="全部">所有状态</option>{Object.entries(decisionLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select><span className="filter-count">{filtered.length} 条结果</span></div></div><div className="review-scroll issue-list">{!issues.length ? <Empty title="本次未返回评审问题">{config.mode === 'mock' ? '该示例没有预设问题，不代表真实评审已通过。' : '以服务返回的结果为准。'}</Empty> : !filtered.length ? <Empty title="没有匹配的建议">尝试清除筛选条件。</Empty> : filtered.map((issue, index) => <article className={`issue-card ${selectedIssue === issue.id ? 'selected' : ''} ${issue.decision !== 'pending' ? 'resolved' : ''}`} key={issue.id}><div className="issue-top"><span className="issue-number">{String(index + 1).padStart(2, '0')}</span><span className="severity">{issue.severity}</span><span className="category">{issue.category}</span><span className={`decision-label ${issue.decision}`}>{decisionLabels[issue.decision]}</span></div><h3><button onClick={() => locate(issue)}>{issue.title}</button></h3><button className="location-link" onClick={() => locate(issue)}><File size={12}/>{locationLabel(issue.location)}<ArrowRight size={12}/></button><div className="evidence"><span className="micro">问题证据</span><p>{issue.evidence}</p></div><details><summary>查看评审标准</summary><p className="small subtle">{issue.standard}</p></details><Diff issue={issue}/><div className="issue-actions"><button className={`button compact ${issue.decision === 'accepted' ? 'chosen' : ''}`} disabled={busy || !canModify} onClick={() => decideIssue(issue, 'accepted')}><Check size={13}/>接受</button><button className="button compact" disabled={busy} onClick={() => decideIssue(issue, 'rejected')}><X size={13}/>拒绝</button><button className="text-button" disabled={busy || !canModify} onClick={() => setModal({ type: 'edit', issue, text: issue.editedText ?? issue.suggestion })}><Pencil size={12}/>手动编辑</button>{issue.decision !== 'pending' && <button className="text-button undo" disabled={busy} onClick={() => decideIssue(issue, 'pending')}>撤销</button>}</div>{!canModify && <p className="micro">{material?.kind === 'pdf' ? 'PDF 只读；可拒绝建议或导出评审记录。' : '新版本不能应用旧版本建议。'}</p>}</article>)}</div><footer className="review-footer"><ShieldCheck size={13}/>每一处修改，由你决定</footer></>}
          </section>
        </div>
      </section>}
    </main>
    {modal && <dialog ref={dialogRef} className="modal" aria-labelledby="modal-title" onCancel={e => { e.preventDefault(); if (!busy) setModal(null); }}><form onSubmit={e => { e.preventDefault(); if (modal.type === 'edit') decideIssue(modal.issue, 'edited', modal.text); else void action(submitModal); }}><div className="modal-header"><h2 id="modal-title">{({ project: modal.type === 'project' && modal.id ? '重命名项目' : '创建项目', 'delete-project': '删除项目', 'delete-material': '删除材料', review: '确认智能体任务', edit: '手动修改建议', text: '编辑文本副本', export: '导出材料与评审' })[modal.type]}</h2><button type="button" className="icon-button" title="关闭弹窗" disabled={busy} onClick={() => setModal(null)}><X size={19}/></button></div><div className="modal-body">
      {modal.type === 'project' && <label className="field">项目名称<input autoFocus maxLength={80} required value={modal.name} onChange={e => setModal({ ...modal, name: e.target.value })}/></label>}
      {modal.type === 'delete-project' && <p>确认从项目列表移除“{modal.name}”？{config.mode === 'real' ? '项目仅归档隐藏，本地原始材料、版本和评审记录全部保留。' : '演示项目及会话记录将移除。'}</p>}
      {modal.type === 'delete-material' && <p>确认从材料列表移除“{modal.material.name}”？{config.mode === 'real' ? '材料仅归档隐藏，原始文件、历史版本和任务记录保留。' : '不会删除磁盘上的原始文件。'}</p>}
      {modal.type === 'review' && <><p className="subtle">材料：{material?.name}</p>{config.mode === 'real' && <><p className="agent-goal-preview">本轮任务：{agentGoal}</p><p className="small subtle">修改任务请先关闭确认窗口，在智能体面板编辑目标后重新预览。</p></>}<label className="field">评审类型<select value={profile} onChange={e => setProfile(e.target.value as Profile)}>{Object.entries(profiles).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><p className="small subtle">{config.mode === 'mock' ? '仅播放固定演示任务，不会调用模型。真实材料评审需接入 A/B/C。' : '请在下方选择离线或真实模型，核对完整选段后确认。默认不选择图片。'}</p>{config.mode === 'real' && material ? <ScopeApproval materialId={material.id} profile={profile} goal={agentGoal} parentTaskId={parentTaskId} onReady={setPrivacy}/> : <label className="check-row"><input type="checkbox" checked={privacy} onChange={e => setPrivacy(e.target.checked)}/>我已了解数据使用范围并同意开始本次评审</label>}</>}
      {modal.type === 'edit' && <><label className="field">原文<textarea readOnly rows={3} value={modal.issue.original}/></label><label className="field">修改后内容<textarea autoFocus required rows={6} value={modal.text} onChange={e => setModal({ ...modal, text: e.target.value })}/></label><p className="small subtle">保存为用户拟定正文草稿，原始文件不覆盖。文本需在材料编辑器保存新版本；Office 请修改副本后上传。</p></>}
      {modal.type === 'text' && <><label className="field">文本内容<textarea autoFocus rows={14} value={modal.text} onChange={e => setModal({ ...modal, text: e.target.value })}/></label><p className="small subtle">以空行分隔内容块。保留原始版本和每次编辑副本，旧评审不会自动应用到新版本。</p></>}
      {modal.type === 'export' && <><p>导出不会覆盖原始文件。下一步将打开系统保存窗口，请确认具体输出路径。</p><label className="field">导出内容<select value={format} onChange={e => setFormat(e.target.value as 'report' | 'text')}><option value="report">评审记录 JSON（含证据、建议与处理状态）</option><option value="text" disabled={material?.kind === 'pdf' || (!['txt', 'md'].includes(material?.kind || ''))}>修改稿 {material?.kind.toUpperCase()}{!['txt', 'md'].includes(material?.kind || '') ? ' · 保格式导出待 A/B' : ''}</option></select></label><p className="small subtle">{format === 'text' ? '导出已保存的文本版本；修改意见不会自动替换正文，须先编辑并保存新版本。' : '记录保留 provider、完整 C 报告与处理状态；Mock 不代表真实模型评审。'} 复杂 Office 自动修改和 PDF 原页渲染尚未支持。</p></>}
    </div><div className="modal-footer"><button type="button" className="button" disabled={busy} onClick={() => setModal(null)}>取消</button><button type="submit" className={`button ${modal.type.startsWith('delete') ? 'destructive' : 'primary'}`} disabled={busy || (modal.type === 'review' && !privacy)}>{busy && <LoaderCircle size={15} className="spin"/>}{modal.type === 'export' ? '选择输出路径' : modal.type.startsWith('delete') ? '确认删除' : modal.type === 'review' ? '开始评审' : '保存'}</button></div></form></dialog>}
  </div>;
}
