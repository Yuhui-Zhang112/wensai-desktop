import type { Block, ConnectionState, Decision, Material, Profile, Project, Task, TaskEvent } from '../domain';
import { validateFile } from '../domain';
import { config } from '../config';
import type { ReviewService } from './types';
export interface ScopePreview {
  taskId: string; versionId: string; provider: 'mock' | 'deepseek'; destination: string;
  textDigest: string; text: { block_id: string; text: string; source: Record<string, unknown> }[]; note: string;
  intentDigest?: string; goal?: string; context?: string; executionMode?: 'pipeline' | 'agent';
}
export const approvals = new Map<string, ScopePreview>();
export class HttpService implements ReviewService {
  private versions = new Map<string, string>();
  async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${config.apiBase}/api/v1/desktop${path}`, {
        ...init, signal: AbortSignal.timeout(60000),
        headers: init.body instanceof FormData ? undefined : { 'Content-Type': 'application/json' },
      });
    } catch { throw new Error('无法连接本地服务，或请求已超时。请确认服务已启动后重试。'); }
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error?.message || `本地服务处理失败（${response.status}）。请检查配置后重试。`);
    }
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
  }
  listProjects() { return this.request<Project[]>('/projects'); }
  createProject(name: string) { return this.request<Project>('/projects', { method: 'POST', body: JSON.stringify({ name }) }); }
  async renameProject(id: string, name: string) { await this.request(`/projects/${encodeURIComponent(id)}`, { method: 'PATCH', body: JSON.stringify({ name }) }); }
  async deleteProject(id: string) { await this.request(`/projects/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async listMaterials(id: string) { const list = await this.request<Material[]>(`/projects/${encodeURIComponent(id)}/materials`); for (const m of list) if (m.versionId) this.versions.set(m.id, m.versionId); return list; }
  async upload(id: string, file: File) { validateFile(file); const form = new FormData(); form.append('file', file); const m = await this.request<Material>(`/projects/${encodeURIComponent(id)}/materials`, { method: 'POST', body: form }); if (m.versionId) this.versions.set(m.id, m.versionId); return m; }
  async deleteMaterial(id: string) { await this.request(`/materials/${encodeURIComponent(id)}`, { method: 'DELETE' }); }
  async saveRevision(id: string, blocks: Block[]) { const result = await this.request<Material>(`/materials/${encodeURIComponent(id)}/revisions`, { method: 'POST', body: JSON.stringify({ blocks, rawText: blocks.map(b => b.text).join('\n\n'), sourceVersionId: this.versions.get(id) }) }); if (result.versionId) this.versions.set(id, result.versionId); return result; }
  async createTask(materialId: string, profile: Profile) {
    const key = `${materialId}:${profile}`;
    const approval = approvals.get(key);
    if (!approval) throw new Error('请先查看完整评审选段并勾选确认。');
    approvals.delete(key);
    return this.request<Task>(`/tasks/${encodeURIComponent(approval.taskId)}/confirm`, { method: 'POST', body: JSON.stringify({ textDigest: approval.textDigest, intentDigest: approval.intentDigest, confirmed: true }) });
  }
  listTasks(id: string) { return this.request<Task[]>(`/materials/${encodeURIComponent(id)}/tasks`); }
  getTask(id: string) { return this.request<Task>(`/tasks/${encodeURIComponent(id)}`); }
  async cancelTask(id: string) { await this.request(`/tasks/${encodeURIComponent(id)}/cancel`, { method: 'POST' }); }
  decide(taskId: string, issueId: string, decision: Decision, editedText?: string) { return this.request<Task>(`/tasks/${encodeURIComponent(taskId)}/issues/${encodeURIComponent(issueId)}`, { method: 'PATCH', body: JSON.stringify({ decision, editedText }) }); }
  subscribe(taskId: string, after: number, event: (e: TaskEvent) => void, state: (s: ConnectionState) => void) {
    let closed = false, cursor = after, socket: WebSocket | undefined, timer: ReturnType<typeof setTimeout> | undefined, retries = 0;
    let queue = Promise.resolve();
    const deliver = async (seq: number) => {
      if (closed || !Number.isSafeInteger(seq) || seq <= cursor) return;
      const task = await this.getTask(taskId);
      if (closed) return;
      cursor = seq; event({ id: seq, task });
    };
    const connect = () => {
      if (closed) return;
      state(retries ? 'reconnecting' : 'connecting');
      const url = new URL(`${config.apiBase}/api/v1/desktop/tasks/${encodeURIComponent(taskId)}/events/ws?after=${cursor}`);
      url.protocol = 'ws:';
      socket = new WebSocket(url);
      socket.onopen = () => { if (!closed) { retries = 0; state('live'); } };
      socket.onmessage = message => {
        queue = queue.then(async () => { try { const value = JSON.parse(message.data); await deliver(value.seq); } catch { if (!closed) state('error'); } });
      };
      socket.onerror = () => socket?.close();
      socket.onclose = e => {
        if (closed) return;
        if ([1008,4404].includes(e.code)) { state('error'); return; }
        state('reconnecting'); retries++;
        timer = setTimeout(async () => {
          try {
            if (closed) return;
            state('polling');
            const page = await this.request<{ items: { seq: number }[] }>(`/tasks/${encodeURIComponent(taskId)}/events?after=${cursor}`);
            for (const item of page.items) await deliver(item.seq);
          } catch { if (!closed) state('error'); }
          connect();
        }, Math.min(1000 * 2 ** Math.min(retries, 4), 15000));
      };
    };
    connect(); return () => { closed = true; if (timer) clearTimeout(timer); socket?.close(); };
  }
  async exportFile(material: Material, task: Task | null, format: 'text' | 'report') {
    const result = await this.request<{ name: string; contentBase64: string }>(`/materials/${encodeURIComponent(material.id)}/exports`, { method: 'POST', body: JSON.stringify({ taskId: task?.id, format, revisionId: material.versionId }) });
    if (!result.name || /[\\/]/.test(result.name)) throw new Error('导出文件名无效。');
    return { name: result.name, bytes: Uint8Array.from(atob(result.contentBase64), c => c.charCodeAt(0)) };
  }
}
