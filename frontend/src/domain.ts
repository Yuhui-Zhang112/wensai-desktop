// D's temporary UI contract. Replace mapping in services/http.ts after A/B/C sign off.
export type MaterialKind = 'docx' | 'pdf' | 'pptx' | 'txt' | 'md';
export type Profile = 'paper' | 'proposal' | 'slides';
export type TaskStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'cancelling';
export type Decision = 'pending' | 'accepted' | 'rejected' | 'edited';
export type Location = { blockId: string; page?: number; slide?: number; paragraph?: number; line_start?: number; line_end?: number };
export interface Block {
  id: string; kind: 'heading' | 'paragraph' | 'table' | 'image'; text: string;
  page?: number; slide?: number; paragraph?: number; rows?: string[][]; imageUrl?: string;
}
export interface Project { id: string; name: string; updatedAt: string }
export interface Revision { id: string; name: string; createdAt: string; blocks: Block[] }
export interface Material {
  id: string; projectId: string; name: string; kind: MaterialKind; createdAt: string;
  blocks: Block[]; revisions: Revision[]; previewState: 'ready' | 'awaiting-parser';
  demo: boolean; versionId?: string; originalVersionId?: string; parseError?: string; rawText?: string;
}
export interface Issue {
  id: string; location: Location; title: string; severity: string; category: string;
  evidence: string; standard: string; original: string; suggestion: string;
  decision: Decision; editedText?: string; suggestionKind?: 'advice';
}
export interface Task {
  id: string; materialId: string; profile: Profile; status: TaskStatus;
  progress: number; eventId: number; issues: Issue[]; error?: string; createdAt: string;
  versionId?: string; provider?: 'mock' | 'deepseek'; progressKnown?: boolean;
  result?: { total_score: number | null; review: { summary: string; dimensions: { id: string; status: string; score: number | null }[] } };
  agent?: { mode: 'agent' | 'pipeline'; goal: string; parentTaskId?: string; answer?: string; termination?: 'finished' | 'needs_input' | 'step_limit';
    steps: { seq: number; action: string; label: string; status: string; observation?: Record<string, unknown>; createdAt: string }[] };
}
export interface TaskEvent { id: number; task: Task }
export type ConnectionState = 'connecting' | 'live' | 'reconnecting' | 'polling' | 'error';
export const profiles: Record<Profile, string> = { paper: '论文评审', proposal: '计划书评审', slides: 'PPT 评审' };
export const statusLabels: Record<TaskStatus, string> = { queued: '等待中', running: '执行中', completed: '已完成', failed: '失败', cancelled: '已取消', cancelling: '正在取消' };
export const decisionLabels: Record<Decision, string> = { pending: '待处理', accepted: '已接受', rejected: '已拒绝', edited: '手动修改' };
export const MAX_FILE_BYTES = 30 * 1024 * 1024;
export function fileKind(name: string): MaterialKind {
  const ext = name.split('.').pop()?.toLowerCase();
  if (!['docx', 'pdf', 'pptx', 'txt', 'md'].includes(ext || '')) throw new Error('暂不支持此文件，请选择 DOCX、PPTX、PDF、TXT 或 Markdown。');
  return ext as MaterialKind;
}
export function validateFile(file: Pick<File, 'name' | 'size'>): MaterialKind {
  const kind = fileKind(file.name);
  if (file.size === 0) throw new Error('文件为空，请选择有内容的材料。');
  if (file.size > MAX_FILE_BYTES) throw new Error('文件超过首版 30 MB 限制，请拆分后导入。');
  return kind;
}
export function locationLabel(location: Partial<Location>) {
  if (location.slide != null) return `幻灯片 ${location.slide}`;
  if (location.line_start != null) return `第 ${location.line_start}–${location.line_end ?? location.line_start} 行`;
  return [location.page != null && `第 ${location.page} 页`, location.paragraph != null && `段落 ${location.paragraph}`].filter(Boolean).join(' · ') || '文档内容';
}
export function applyIssues(blocks: Block[], issues: Issue[]): Block[] {
  const active = issues.filter(i => i.decision === 'accepted' || i.decision === 'edited');
  const counts = new Map<string, number>();
  for (const issue of active) counts.set(issue.location.blockId, (counts.get(issue.location.blockId) || 0) + 1);
  if ([...counts.values()].some(count => count > 1)) throw new Error('同一段落有多条已接受建议，请只保留一条，或手动合并后再导出。');
  return blocks.map(block => {
    const issue = active.find(i => i.location.blockId === block.id);
    if (!issue) return { ...block };
    if (issue.original !== block.text) throw new Error('原文已变化，建议与当前版本不一致，请重新评审。');
    return { ...block, text: issue.decision === 'edited' ? issue.editedText ?? issue.suggestion : issue.suggestion };
  });
}
export function plainText(blocks: Block[]) {
  return blocks.map(b => b.kind === 'table' ? (b.rows || []).map(r => r.join('\t')).join('\n') : b.text).join('\n\n');
}
export function diffTokens(before: string, after: string) {
  let start = 0;
  while (start < Math.min(before.length, after.length) && before[start] === after[start]) start++;
  // Avoid cutting a Unicode surrogate pair in half.
  if (start > 0 && /[\uD800-\uDBFF]/.test(before[start - 1])) start--;
  let end = 0;
  while (end < Math.min(before.length, after.length) - start && before[before.length - 1 - end] === after[after.length - 1 - end]) end++;
  if (end > 0 && /[\uDC00-\uDFFF]/.test(before[before.length - end])) end--;
  return { prefix: before.slice(0, start), removed: before.slice(start, before.length - end), added: after.slice(start, after.length - end), suffix: end ? before.slice(-end) : '' };
}
