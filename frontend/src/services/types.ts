import type { Block, ConnectionState, Decision, Material, Profile, Project, Task, TaskEvent } from '../domain';
export interface ReviewService {
  listProjects(): Promise<Project[]>;
  createProject(name: string): Promise<Project>;
  renameProject(id: string, name: string): Promise<void>;
  deleteProject(id: string): Promise<void>;
  listMaterials(projectId: string): Promise<Material[]>;
  upload(projectId: string, file: File): Promise<Material>;
  deleteMaterial(id: string): Promise<void>;
  saveRevision(id: string, blocks: Block[]): Promise<Material>;
  createTask(materialId: string, profile: Profile): Promise<Task>;
  listTasks(materialId: string): Promise<Task[]>;
  getTask(id: string): Promise<Task>;
  cancelTask(id: string): Promise<void>;
  decide(taskId: string, issueId: string, decision: Decision, editedText?: string): Promise<Task>;
  subscribe(taskId: string, after: number, event: (e: TaskEvent) => void, state: (s: ConnectionState) => void): () => void;
  exportFile(material: Material, task: Task | null, format: 'text' | 'report'): Promise<{ name: string; bytes: Uint8Array }>;
}
