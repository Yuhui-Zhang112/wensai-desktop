import { applyIssues, plainText, validateFile } from '../domain';
import type { Block, ConnectionState, Decision, Material, Profile, Project, Task, TaskEvent } from '../domain';
import type { ReviewService } from './types';
import { sampleIssues, seedMaterials } from './fixtures';
const clone = <T,>(value: T): T => structuredClone(value);
const now = () => new Date().toISOString();
const id = () => crypto.randomUUID();
const delay = () => new Promise(resolve => setTimeout(resolve, 160));
// Deliberately memory-only: no user material or API key is put into localStorage.
export class MockService implements ReviewService {
  projects: Project[] = [{ id: 'p1', name: '城市公共空间研究', updatedAt: now() }];
  materials = seedMaterials();
  tasks: Task[] = [{ id: 't1', materialId: 'm1', profile: 'paper', status: 'completed', progress: 100, eventId: 1, createdAt: now(), issues: sampleIssues(this.materials[0]) }];
  failure = false;
  disconnected = false;
  failNextTask = false;
  private failingTaskIds = new Set<string>();
  configureAgentTask(taskId: string, goal: string, parentTaskId?: string) {
    const task=this.task(taskId);
    task.provider='mock';
    task.agent={mode:'agent',goal,parentTaskId,steps:[]};
    return clone(task);
  }
  private check() { if (this.failure) throw new Error('模拟服务暂时不可用。请关闭“模拟请求失败”后重试。'); }
  private task(id: string) { const task = this.tasks.find(t => t.id === id); if (!task) throw new Error('任务不存在，请返回材料页重试。'); return task; }
  async listProjects() { await delay(); this.check(); return clone(this.projects); }
  async createProject(name: string) { this.check(); const project = { id: id(), name: name.trim(), updatedAt: now() }; this.projects.push(project); return clone(project); }
  async renameProject(id: string, name: string) { this.check(); const p = this.projects.find(p => p.id === id); if (p) { p.name = name.trim(); p.updatedAt = now(); } }
  async deleteProject(id: string) { this.check(); const ids = this.materials.filter(m => m.projectId === id).map(m => m.id); this.projects = this.projects.filter(p => p.id !== id); this.materials = this.materials.filter(m => m.projectId !== id); this.tasks = this.tasks.filter(t => !ids.includes(t.materialId)); }
  async listMaterials(projectId: string) { await delay(); this.check(); return clone(this.materials.filter(m => m.projectId === projectId)); }
  async upload(projectId: string, file: File) {
    this.check(); const kind = validateFile(file); const text = kind === 'txt' || kind === 'md' ? await file.text() : '';
    const material: Material = { id: id(), projectId, name: file.name, kind, createdAt: now(),
      blocks: text ? text.split(/\r?\n\s*\r?\n/).map((text, n) => ({ id: id(), kind: text.startsWith('#') ? 'heading' : 'paragraph', text, paragraph: n + 1 })) : [],
      revisions: [], previewState: ['txt', 'md'].includes(kind) ? 'ready' : 'awaiting-parser', demo: false };
    this.materials.push(material); return clone(material);
  }
  async deleteMaterial(id: string) { this.check(); this.materials = this.materials.filter(m => m.id !== id); this.tasks = this.tasks.filter(t => t.materialId !== id); }
  async saveRevision(id: string, blocks: Block[]) {
    this.check(); const m = this.materials.find(m => m.id === id); if (!m) throw new Error('材料不存在。');
    if (!['txt', 'md'].includes(m.kind)) throw new Error('此格式只能通过评审建议修改，不支持直接编辑。');
    m.revisions.push({ id: crypto.randomUUID(), name: `编辑版本 ${m.revisions.length + 1}`, createdAt: now(), blocks: clone(blocks) });
    return clone(m);
  }
  async createTask(materialId: string, profile: Profile) {
    this.check(); const material = this.materials.find(m => m.id === materialId);
    if (!material) throw new Error('材料不存在。');
    if (!material.demo) throw new Error('当前为演示模式，真实材料评审需要接入 A/B/C 服务，不会生成模拟结论。');
    const task: Task = { id: id(), materialId, profile, status: 'queued', progress: 0, eventId: 1, issues: [], createdAt: now() };
    if (this.failNextTask) { this.failingTaskIds.add(task.id); this.failNextTask = false; }
    this.tasks.unshift(task); return clone(task);
  }
  async listTasks(materialId: string) { await delay(); this.check(); return clone(this.tasks.filter(t => t.materialId === materialId)); }
  async getTask(id: string) { this.check(); return clone(this.task(id)); }
  async cancelTask(id: string) { this.check(); const task = this.task(id); if (['queued', 'running'].includes(task.status)) { task.status = 'cancelled'; task.eventId++; } }
  async decide(taskId: string, issueId: string, decision: Decision, editedText?: string) {
    this.check(); const task = this.task(taskId); const issue = task.issues.find(i => i.id === issueId);
    if (!issue) throw new Error('评审建议不存在。');
    const material = this.materials.find(m => m.id === task.materialId);
    if (material?.kind === 'pdf' && ['accepted', 'edited'].includes(decision)) throw new Error('PDF 为只读材料。');
    issue.decision = decision; issue.editedText = editedText; task.eventId++; return clone(task);
  }
  subscribe(taskId: string, _after: number, event: (e: TaskEvent) => void, state: (s: ConnectionState) => void) {
    state('live'); let offline = false;
    const timer = setInterval(() => {
      if (this.disconnected || this.failure) { state(this.failure ? 'error' : 'reconnecting'); offline = true; return; }
      if (offline) { state('live'); offline = false; }
      const task = this.tasks.find(t => t.id === taskId); if (!task) return;
      if (task.status === 'queued') task.status = 'running';
      else if (task.status === 'running') {
        if (this.failingTaskIds.has(task.id)) { task.status = 'failed'; task.error = '模拟评审失败。真实错误由 A/C 返回，可重新评审。'; this.failingTaskIds.delete(task.id); }
        else {
        task.progress = Math.min(100, task.progress + 20);
        if (task.agent) {
          const n=Math.floor(task.progress/20);
          const actions=['inspect_scope','search_standards','review_content','finish'];
          const labels=['读取材料（界面预设示例）','检索标准（界面预设示例）','证据评审（界面预设示例）','形成结论（界面预设示例）'];
          task.agent.steps=actions.slice(0,Math.min(n,4)).map((action,index)=>({seq:index+1,action,label:labels[index],status:'completed',createdAt:now(),observation:{note:'仅为单文件界面演示的固定记录，没有执行真实工具或模型。'}}));
        }
        if (task.progress === 100) { task.status = 'completed'; task.issues = sampleIssues(this.materials.find(m => m.id === task.materialId)!); if(task.agent){task.agent.answer='固定界面示例：先补充证据与适用范围，再调整结论。此处不是模型输出；完整智能体需通过本地后端运行。';task.agent.termination='finished';} }
        }
      }
      task.eventId++; event({ id: task.eventId, task: clone(task) });
    }, 900);
    return () => clearInterval(timer);
  }
  async exportFile(material: Material, task: Task | null, format: 'text' | 'report') {
    this.check();
    if (format === 'text' && material.kind === 'pdf') throw new Error('PDF 不提供直接修改，请导出评审记录。');
    if (format === 'text' && !['txt', 'md'].includes(material.kind)) throw new Error('DOCX/PPTX 保格式导出需 A/B 服务，演示版只支持导出评审记录。');
    const blocks = material.revisions.at(-1)?.blocks || material.blocks;
    const content = format === 'report' ? JSON.stringify({ mode: 'demo', source: material.name, task, note: '示例数据，仅用于界面验收，不代表真实评审；原文件未修改。' }, null, 2) : plainText(applyIssues(blocks, task?.issues || []));
    const stem = material.name.replace(/\.[^.]+$/, '');
    return { name: format === 'report' ? `${stem}-评审记录.json` : `${stem}-修改稿.${material.kind}`, bytes: new TextEncoder().encode(content) };
  }
}
